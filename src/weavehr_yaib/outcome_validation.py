"""Comparison helpers for derived outcome/cohort validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import polars as pl


@dataclass(frozen=True)
class OutcomeComparison:
    """Result of a row-level categorical outcome comparison."""

    summary: pl.DataFrame
    disagreements: pl.DataFrame


def _assert_unique_keys(df: pl.DataFrame, keys: Sequence[str], label: str) -> None:
    duplicates = (
        df.group_by(list(keys))
        .len()
        .filter(pl.col("len") > 1)
    )
    if duplicates.height:
        raise ValueError(
            f"{label} contains {duplicates.height} duplicated outcome key(s) "
            f"for {list(keys)!r}."
        )


def compare_categorical_outcome(
    weavehr: pl.DataFrame,
    reference: pl.DataFrame,
    *,
    keys: Sequence[str],
    weavehr_value: str,
    reference_value: str,
) -> OutcomeComparison:
    """Compare one categorical outcome on explicitly declared unique keys.

    Nulls are treated as values for agreement purposes:

    * non-null / non-null: values must be equal;
    * null / null: agreement;
    * null / non-null or non-null / null: disagreement.

    Rows present on only one side are reported separately.
    """
    if not keys:
        raise ValueError("At least one comparison key is required.")

    keys = list(keys)
    _assert_unique_keys(weavehr, keys, "WeavEHR")
    _assert_unique_keys(reference, keys, "reference")

    w = weavehr.select(
        keys + [pl.col(weavehr_value).alias("weavehr_value")]
    ).with_columns(pl.lit(True).alias("_weavehr_row"))

    r = reference.select(
        keys + [pl.col(reference_value).alias("reference_value")]
    ).with_columns(pl.lit(True).alias("_reference_row"))

    joined = (
        w.join(
            r,
            on=keys,
            how="full",
            coalesce=True,
        )
        .with_columns(
            pl.col("_weavehr_row").fill_null(False),
            pl.col("_reference_row").fill_null(False),
        )
    )

    weavehr_row = pl.col("_weavehr_row")
    reference_row = pl.col("_reference_row")
    shared_row = weavehr_row & reference_row
    only_weavehr_row = weavehr_row & ~reference_row
    only_reference_row = ~weavehr_row & reference_row

    both_present = (
        shared_row
        & pl.col("weavehr_value").is_not_null()
        & pl.col("reference_value").is_not_null()
    )
    both_null = (
        shared_row
        & pl.col("weavehr_value").is_null()
        & pl.col("reference_value").is_null()
    )
    only_weavehr_value = (
        shared_row
        & pl.col("weavehr_value").is_not_null()
        & pl.col("reference_value").is_null()
    )
    only_reference_value = (
        shared_row
        & pl.col("weavehr_value").is_null()
        & pl.col("reference_value").is_not_null()
    )
    unequal_values = both_present & (
        pl.col("weavehr_value") != pl.col("reference_value")
    )

    summary = joined.select(
        pl.lit(weavehr.height).alias("weavehr_rows"),
        pl.lit(reference.height).alias("reference_rows"),
        pl.len().alias("joined_rows"),
        shared_row.sum().alias("shared_rows"),
        only_weavehr_row.sum().alias("only_weavehr_rows"),
        only_reference_row.sum().alias("only_reference_rows"),
        both_present.sum().alias("both_non_null"),
        both_null.sum().alias("both_null"),
        only_weavehr_value.sum().alias("only_weavehr_value"),
        only_reference_value.sum().alias("only_reference_value"),
        (both_present & ~unequal_values).sum().alias("equal_non_null"),
        unequal_values.sum().alias("different_non_null"),
    ).with_columns(
        (
            pl.col("equal_non_null") + pl.col("both_null")
        ).alias("equal_including_null")
    )

    disagreements = (
        joined.filter(
            only_weavehr_row
            | only_reference_row
            | only_weavehr_value
            | only_reference_value
            | unequal_values
        )
        .drop("_weavehr_row", "_reference_row")
    )

    return OutcomeComparison(
        summary=summary,
        disagreements=disagreements,
    )


def write_outcome_comparison(
    result: OutcomeComparison,
    out_dir: str | Path,
) -> tuple[Path, Path]:
    """Persist summary and disagreement rows as CSV files."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    summary_path = out / "summary.csv"
    disagreements_path = out / "disagreements.csv"

    result.summary.write_csv(summary_path)
    result.disagreements.write_csv(disagreements_path)

    return summary_path, disagreements_path


def _blank_to_null(column: str) -> pl.Expr:
    """Normalize empty/whitespace-only categorical values to null."""
    value = pl.col(column).cast(pl.String)
    return (
        pl.when(value.str.strip_chars() == "")
        .then(None)
        .otherwise(value)
    )


def normalize_mimic_mortality_weavehr(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize WeavEHR MIMIC-IV in-hospital mortality output.

    WeavEHR emits the admission-level event at hospital discharge time.
    """
    return df.select(
        pl.col("subject_id").cast(pl.Int64),
        pl.col("time").alias("dischtime"),
        pl.col("numeric_value").cast(pl.Int64).alias("mortality"),
    )


def normalize_mimic_mortality_reference(df: pl.DataFrame) -> pl.DataFrame:
    """Reproduce the RICU MIMIC-IV death definition.

    RICU defines death as ``hospital_expire_flag == 1`` and indexes the
    resulting admission-level outcome at ``dischtime``.
    """
    flag = pl.col("hospital_expire_flag")
    return df.select(
        pl.col("subject_id").cast(pl.Int64),
        pl.col("dischtime")
        .dt.replace_time_zone(None)
        .cast(pl.Datetime("us"))
        .alias("dischtime"),
        pl.when(flag.is_null())
        .then(None)
        .otherwise((flag == 1).cast(pl.Int64))
        .alias("mortality"),
    )


def normalize_eicu_mortality_weavehr(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize WeavEHR eICU mortality to one row per hospital stay."""
    return df.select(
        pl.col("subject_id").cast(pl.Int64).alias("patienthealthsystemstayid"),
        _blank_to_null("text_value").alias("status"),
    )


def normalize_eicu_mortality_reference(df: pl.DataFrame) -> pl.DataFrame:
    """Collapse eICU ICU stays to the hospital-admission mortality level.

    RICU defines death from ``hospitaldischargestatus == "Expired"``. Several
    ICU stays may belong to one ``patienthealthsystemstayid``; all available
    hospital discharge statuses for such a stay must agree.
    """
    clean = df.select(
        pl.col("patienthealthsystemstayid").cast(pl.Int64),
        _blank_to_null("hospitaldischargestatus").alias("_status"),
    )

    conflicts = (
        clean.filter(pl.col("_status").is_not_null())
        .group_by("patienthealthsystemstayid")
        .agg(pl.col("_status").n_unique().alias("n_status"))
        .filter(pl.col("n_status") > 1)
    )
    if conflicts.height:
        raise ValueError(
            "eICU reference contains conflicting non-null hospital discharge "
            f"statuses for {conflicts.height} hospital stay(s)."
        )

    return (
        clean.group_by("patienthealthsystemstayid")
        .agg(pl.col("_status").drop_nulls().first().alias("status"))
        .sort("patienthealthsystemstayid")
    )


def normalize_hirid_mortality_weavehr(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize WeavEHR HiRID discharge status."""
    return df.select(
        pl.col("subject_id").cast(pl.Int64).alias("patientid"),
        _blank_to_null("text_value").alias("status"),
    )


def normalize_hirid_mortality_reference(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize the HiRID general-table discharge status used by RICU."""
    return df.select(
        pl.col("patientid").cast(pl.Int64),
        _blank_to_null("discharge_status").alias("status"),
    )


__all__ = [
    "OutcomeComparison",
    "normalize_mimic_mortality_weavehr",
    "normalize_mimic_mortality_reference",
    "normalize_eicu_mortality_weavehr",
    "normalize_eicu_mortality_reference",
    "normalize_hirid_mortality_weavehr",
    "normalize_hirid_mortality_reference",
    "compare_categorical_outcome",
    "write_outcome_comparison",
]
