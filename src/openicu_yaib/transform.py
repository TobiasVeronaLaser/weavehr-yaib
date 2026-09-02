"""Core OpenICU -> YAIB/RICU dynamic table transformation."""

from __future__ import annotations

from functools import reduce
from pathlib import Path
from typing import Literal

import polars as pl

from .concepts import DYNAMIC_VARS, RICU_TO_OPENICU
from .io import (
    find_concept_file,
    scan_dataset_stays,
    scan_mimic_icustays,
    scan_openicu_concept,
    scan_openicu_dynamic_concept,
    scan_openicu_subject_concept_hours,
)
from .ricu_meta import RicuConceptMeta
from .stays import DatasetStaySpec

AggregationMode = Literal["mean", "ricu"]
MissingConcepts = Literal["warn", "fail", "ignore"]
GridEndRounding = Literal["floor", "ceil"]


def _range_filter_expr(ricu_meta: RicuConceptMeta, ricu_name: str) -> pl.Expr:
    lower, upper = ricu_meta.range_for(ricu_name)
    expr = pl.col("numeric_value").is_not_null()
    if lower is not None:
        expr = expr & (pl.col("numeric_value") >= float(lower))
    if upper is not None:
        expr = expr & (pl.col("numeric_value") <= float(upper))
    return expr


def _agg_expr(ricu_name: str, output_col: str, aggregate: str) -> pl.Expr:
    aggregate = aggregate.lower()
    value = pl.col("numeric_value")
    if aggregate == "mean":
        return value.mean().alias(output_col)
    if aggregate == "median":
        return value.median().alias(output_col)
    if aggregate == "sum":
        return value.sum().alias(output_col)
    if aggregate == "min":
        return value.min().alias(output_col)
    if aggregate == "max":
        return value.max().alias(output_col)
    if aggregate == "first":
        return value.first().alias(output_col)
    if aggregate == "last":
        return value.last().alias(output_col)
    raise ValueError(f"Unsupported aggregation for {ricu_name!r}: {aggregate!r}")


def map_events_to_stays(
    events: pl.LazyFrame,
    stays: pl.LazyFrame,
    *,
    filter_to_icu_window: bool = True,
) -> pl.LazyFrame:
    """Map subject-level OpenICU concept events to ICU stays.

    If ``filter_to_icu_window`` is true, an event is assigned to a stay iff
    ``event.time >= intime`` and ``event.time <= outtime``. The output time is
    the floored number of hours since ICU admission.
    """
    mapped = events.join(stays, on="subject_id", how="inner")

    if filter_to_icu_window:
        mapped = mapped.filter(
            (pl.col("time") >= pl.col("intime"))
            & (pl.col("outtime").is_null() | (pl.col("time") <= pl.col("outtime")))
        )

    return (
        mapped.with_columns(
            (
                (pl.col("time") - pl.col("intime")).dt.total_seconds().cast(pl.Float64) / 3600.0
            ).alias("diff_hours")
        )
        .with_columns(pl.col("diff_hours").floor().cast(pl.Int64).alias("time"))
        .filter(pl.col("time") >= 0)
        .select("stay_id", "time", "numeric_value")
    )


def map_subject_events_to_dataset_stays(
    events: pl.LazyFrame,
    stays: pl.LazyFrame,
    *,
    filter_to_icu_window: bool = True,
) -> pl.LazyFrame:
    """Map normalized subject events to normalized dataset ICU stays."""
    if "visit_occurrence_id" in events.collect_schema().names():
        mapped = (
            events.with_columns(
                pl.col("visit_occurrence_id").cast(pl.Int64).alias("stay_id")
            )
            .join(stays, on=["subject_id", "stay_id"], how="inner")
        )
    else:
        mapped = events.join(stays, on="subject_id", how="inner")

    if filter_to_icu_window:
        mapped = mapped.filter(
            (pl.col("time_hours") >= pl.col("intime_hours"))
            & (
                pl.col("outtime_hours").is_null()
                | (pl.col("time_hours") <= pl.col("outtime_hours"))
            )
        )
    return (
        mapped.with_columns(
            (pl.col("time_hours") - pl.col("intime_hours")).floor().cast(pl.Int64).alias("time")
        )
        .filter(pl.col("time") >= 0)
        .select("stay_id", "time", "numeric_value")
    )


def aggregate_dataset_concept_hourly(
    *,
    concept_file: str | Path,
    stays: pl.LazyFrame,
    stay_spec: DatasetStaySpec,
    ricu_name: str,
    ricu_meta: RicuConceptMeta,
    aggregation_mode: AggregationMode = "ricu",
    filter_to_icu_window: bool = True,
) -> pl.LazyFrame:
    """Load and aggregate one concept using a dataset-specific stay definition."""
    events = scan_openicu_subject_concept_hours(
        concept_file, numeric_scale_hours=stay_spec.numeric_time_scale_hours
    ).filter(_range_filter_expr(ricu_meta, ricu_name))
    mapped = map_subject_events_to_dataset_stays(
        events, stays, filter_to_icu_window=filter_to_icu_window
    )
    aggregate = (
        ricu_meta.aggregate_for(ricu_name, default="median")
        if aggregation_mode == "ricu"
        else "mean"
    )
    return (
        mapped.group_by("stay_id", "time")
        .agg(_agg_expr(ricu_name=ricu_name, output_col=ricu_name, aggregate=aggregate))
        .select("stay_id", "time", ricu_name)
    )


def aggregate_concept_hourly(
    *,
    concept_file: str | Path,
    stays: pl.LazyFrame,
    ricu_name: str,
    ricu_meta: RicuConceptMeta,
    aggregation_mode: AggregationMode = "ricu",
    filter_to_icu_window: bool = True,
) -> pl.LazyFrame:
    """Load, range-filter, stay-map and aggregate one dynamic concept."""
    events = scan_openicu_concept(concept_file).filter(_range_filter_expr(ricu_meta, ricu_name))
    mapped = map_events_to_stays(events, stays, filter_to_icu_window=filter_to_icu_window)
    aggregate = "mean"
    if aggregation_mode == "ricu":
        aggregate = ricu_meta.aggregate_for(ricu_name, default="median")

    return (
        mapped.group_by("stay_id", "time")
        .agg(_agg_expr(ricu_name=ricu_name, output_col=ricu_name, aggregate=aggregate))
        .select("stay_id", "time", ricu_name)
    )


def aggregate_identity_concept_hourly(
    *,
    concept_file: str | Path,
    stay_spec: DatasetStaySpec,
    ricu_name: str,
    ricu_meta: RicuConceptMeta,
    aggregation_mode: AggregationMode = "ricu",
) -> pl.LazyFrame:
    """Treat OpenICU subject_id as the ICU stay ID and time as relative hours."""
    events = scan_openicu_subject_concept_hours(
        concept_file, numeric_scale_hours=stay_spec.numeric_time_scale_hours
    ).filter(_range_filter_expr(ricu_meta, ricu_name))
    aggregate = (
        ricu_meta.aggregate_for(ricu_name, default="median")
        if aggregation_mode == "ricu"
        else "mean"
    )
    return (
        events.with_columns(
            pl.col("subject_id").alias("stay_id"),
            pl.col("time_hours").floor().cast(pl.Int64).alias("time"),
        )
        .filter(pl.col("time") >= 0)
        .group_by("stay_id", "time")
        .agg(_agg_expr(ricu_name=ricu_name, output_col=ricu_name, aggregate=aggregate))
        .select("stay_id", "time", ricu_name)
    )


def aggregate_dynamic_concept_hourly(
    *,
    concept_file: str | Path,
    ricu_name: str,
    ricu_meta: RicuConceptMeta,
    aggregation_mode: AggregationMode = "ricu",
) -> pl.LazyFrame:
    """Load, range-filter and aggregate one already stay/time-indexed dynamic concept.

    This path intentionally does not read ``icustays.csv.gz`` and does not
    modify the induced integer ``time`` column. It expects the concept parquet
    to already contain ``stay_id``, ``time`` and ``numeric_value``.
    """
    events = scan_openicu_dynamic_concept(concept_file).filter(
        _range_filter_expr(ricu_meta, ricu_name)
    )
    aggregate = "mean"
    if aggregation_mode == "ricu":
        aggregate = ricu_meta.aggregate_for(ricu_name, default="median")

    return (
        events.group_by("stay_id", "time")
        .agg(_agg_expr(ricu_name=ricu_name, output_col=ricu_name, aggregate=aggregate))
        .select("stay_id", "time", ricu_name)
    )


def make_yaib_grid(
    stays: pl.LazyFrame,
    max_hours: int | None = 168,
    *,
    end_rounding: GridEndRounding = "floor",
) -> pl.LazyFrame:
    """Create a YAIB-like hourly stay grid.

    Creates rows ``time = 0, 1, ..., end_time`` for every ICU stay.

    ``end_rounding='floor'`` is the current default because this matched the
    observed ``ricu::stay_windows('miiv', interval = hours(1))`` end indices in
    debugging. Use ``'ceil'`` only if you explicitly want the older behavior.
    """
    if end_rounding not in {"floor", "ceil"}:
        raise ValueError("end_rounding must be 'floor' or 'ceil'.")

    los_end_expr = (
        pl.col("los_hours").floor() if end_rounding == "floor" else pl.col("los_hours").ceil()
    )

    grid = stays.with_columns(
        ((pl.col("outtime") - pl.col("intime")).dt.total_seconds().cast(pl.Float64) / 3600.0).alias(
            "los_hours"
        )
    ).with_columns(
        pl.when(pl.col("los_hours").is_null() | (pl.col("los_hours") < 0))
        .then(0)
        .otherwise(los_end_expr.cast(pl.Int64))
        .alias("los_end")
    )

    if max_hours is None:
        grid = grid.with_columns(pl.col("los_end").alias("end_time"))
    else:
        grid = grid.with_columns(pl.min_horizontal("los_end", pl.lit(max_hours)).alias("end_time"))

    return (
        grid.select("stay_id", pl.int_ranges(0, pl.col("end_time") + 1).alias("time"))
        .explode("time")
        .with_columns(pl.col("time").cast(pl.Int64))
    )


def outer_join_concepts(concept_tables: list[pl.LazyFrame]) -> pl.LazyFrame:
    """Full-join all concept tables on stay_id/time."""
    if not concept_tables:
        raise ValueError("No concept tables to join.")
    return reduce(
        lambda left, right: left.join(right, on=["stay_id", "time"], how="full", coalesce=True),
        concept_tables,
    )


def build_dynamic_table(
    *,
    concept_root: str | Path,
    icustays_csv: str | Path | None = None,
    stay_spec: DatasetStaySpec | None = None,
    normalized_stays: pl.LazyFrame | None = None,
    ricu_concept_dict: str | Path | None = None,
    dataset: str = "mimic-iv",
    version: str | None = None,
    dynamic_vars: list[str] | None = None,
    concept_mapping: dict[str, str] | None = None,
    aggregation_mode: AggregationMode = "ricu",
    include_grid: bool = True,
    max_hours: int | None = 168,
    grid_end_rounding: GridEndRounding = "floor",
    filter_to_icu_window: bool = True,
    missing_concepts: MissingConcepts = "warn",
) -> pl.LazyFrame:
    """Build the wide YAIB/RICU-like dynamic table.

    Returns a lazy frame with columns ``stay_id``, ``time`` and one column per
    successfully loaded dynamic concept abbreviation.

    If ``icustays_csv`` is provided, subject-level concept timestamps are mapped
    to ICU stays. If ``icustays_csv=None``, concept parquets must already contain
    ``stay_id`` and induced integer ``time``; the function then only aggregates
    duplicate keys and joins concepts into the wide format.
    """
    vars_ = dynamic_vars or DYNAMIC_VARS
    mapping = concept_mapping or RICU_TO_OPENICU
    ricu_meta = RicuConceptMeta.from_json(ricu_concept_dict)

    if icustays_csv is None and normalized_stays is None and include_grid:
        raise ValueError(
            "include_grid=True requires a dataset ICU-stay table. "
            "Set OPENICU_YAIB_<DATASET>_STAYS or OPENICU_YAIB_DATA_ROOT."
        )

    if normalized_stays is not None:
        stays = normalized_stays
        dataset_stays = True
    elif icustays_csv is not None and stay_spec is not None:
        stays = scan_dataset_stays(icustays_csv, stay_spec)
        dataset_stays = True
    elif icustays_csv is not None:
        stays = scan_mimic_icustays(icustays_csv)
        dataset_stays = False
    else:
        stays = None
        dataset_stays = False

    concept_tables: list[pl.LazyFrame] = []
    missing: list[tuple[str, str]] = []

    for ricu_name in vars_:
        openicu_name = mapping.get(ricu_name)
        if openicu_name is None:
            missing.append((ricu_name, "no OpenICU mapping"))
            continue

        concept_file = find_concept_file(
            concept_root, openicu_name, dataset=dataset, version=version
        )
        if concept_file is None:
            missing.append((ricu_name, f"missing parquet for OpenICU concept {openicu_name!r}"))
            continue

        if stays is None:
            if stay_spec is not None and stay_spec.subject_is_stay:
                concept_tables.append(
                    aggregate_identity_concept_hourly(
                        concept_file=concept_file,
                        stay_spec=stay_spec,
                        ricu_name=ricu_name,
                        ricu_meta=ricu_meta,
                        aggregation_mode=aggregation_mode,
                    )
                )
            else:
                concept_tables.append(
                    aggregate_dynamic_concept_hourly(
                        concept_file=concept_file,
                        ricu_name=ricu_name,
                        ricu_meta=ricu_meta,
                        aggregation_mode=aggregation_mode,
                    )
                )
        else:
            if dataset_stays:
                assert stay_spec is not None
                concept_tables.append(
                    aggregate_dataset_concept_hourly(
                        concept_file=concept_file,
                        stays=stays,
                        stay_spec=stay_spec,
                        ricu_name=ricu_name,
                        ricu_meta=ricu_meta,
                        aggregation_mode=aggregation_mode,
                        filter_to_icu_window=filter_to_icu_window,
                    )
                )
            else:
                concept_tables.append(
                    aggregate_concept_hourly(
                        concept_file=concept_file,
                        stays=stays,
                        ricu_name=ricu_name,
                        ricu_meta=ricu_meta,
                        aggregation_mode=aggregation_mode,
                        filter_to_icu_window=filter_to_icu_window,
                    )
                )

    if missing:
        msg = "Missing concepts:\n" + "\n".join(f"- {k}: {reason}" for k, reason in missing)
        if missing_concepts == "fail":
            raise FileNotFoundError(msg)
        if missing_concepts == "warn":
            print(f"WARNING: {msg}")

    wide = outer_join_concepts(concept_tables)

    if include_grid:
        assert stays is not None
        if dataset_stays:
            normalized = stays.rename(
                {"intime_hours": "intime", "outtime_hours": "outtime"}
            ).with_columns(pl.col("intime").cast(pl.Float64), pl.col("outtime").cast(pl.Float64))
            los = normalized.with_columns((pl.col("outtime") - pl.col("intime")).alias("los_hours"))
            end_expr = pl.col("los_hours").floor().cast(pl.Int64)
            if max_hours is not None:
                end_expr = pl.min_horizontal(end_expr, pl.lit(max_hours))
            grid = (
                los.with_columns(
                    pl.when(pl.col("los_hours").is_null() | (pl.col("los_hours") < 0))
                    .then(0 if max_hours is None else max_hours)
                    .otherwise(end_expr)
                    .alias("end_time")
                )
                .select("stay_id", pl.int_ranges(0, pl.col("end_time") + 1).alias("time"))
                .explode("time")
                .with_columns(pl.col("time").cast(pl.Int64))
            )
        else:
            grid = make_yaib_grid(stays, max_hours=max_hours, end_rounding=grid_end_rounding)
        wide = grid.join(wide, on=["stay_id", "time"], how="left")
    elif max_hours is not None:
        wide = wide.filter(pl.col("time") <= max_hours)

    present = wide.collect_schema().names()
    ordered_cols = ["stay_id", "time"] + [v for v in vars_ if v in present]
    return wide.select(ordered_cols).sort("stay_id", "time")


def write_dynamic_table(
    *,
    output_path: str | Path,
    **kwargs,
) -> None:
    """Build and write the dynamic table as parquet."""
    lf = build_dynamic_table(**kwargs)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lf.sink_parquet(out)
