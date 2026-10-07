"""Compare WeavEHR-generated dynamic tables with YAIB/RICU references."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .concepts import DYNAMIC_VARS


def scan_dyn(path: str | Path) -> pl.LazyFrame:
    return pl.scan_parquet(path)


def normalize_reference_columns(
    reference: pl.LazyFrame,
    *,
    id_col: str = "stay_id",
    time_col: str = "time",
) -> pl.LazyFrame:
    """Normalize a reference dynamic table to stay_id/time names.

    Use this for RICU exports where the time column is called charttime.
    """
    rename: dict[str, str] = {}
    if id_col != "stay_id":
        rename[id_col] = "stay_id"
    if time_col != "time":
        rename[time_col] = "time"
    lf = reference.rename(rename) if rename else reference
    return lf.with_columns(
        [
            pl.col("stay_id").cast(pl.Int64),
            pl.col("time").cast(pl.Int64),
        ]
    )


def schema_report(
    weavehr: pl.LazyFrame, reference: pl.LazyFrame, dynamic_vars: list[str] | None = None
) -> dict[str, list[str]]:
    vars_ = dynamic_vars or DYNAMIC_VARS
    expected = ["stay_id", "time"] + vars_
    weavehr_cols = weavehr.collect_schema().names()
    ref_cols = reference.collect_schema().names()
    return {
        "missing_in_weavehr": [c for c in expected if c not in weavehr_cols],
        "missing_in_reference": [c for c in expected if c not in ref_cols],
        "extra_in_weavehr": [c for c in weavehr_cols if c not in expected],
        "extra_in_reference": [c for c in ref_cols if c not in expected],
        "common_dynamic_vars": [c for c in vars_ if c in weavehr_cols and c in ref_cols],
    }


def table_summary(df: pl.LazyFrame, name: str) -> pl.DataFrame:
    return df.select(
        [
            pl.lit(name).alias("table"),
            pl.len().alias("n_rows"),
            pl.col("stay_id").n_unique().alias("n_stays"),
            pl.col("time").min().alias("min_time"),
            pl.col("time").max().alias("max_time"),
        ]
    ).collect()


def key_overlap_report(weavehr: pl.LazyFrame, reference: pl.LazyFrame) -> pl.DataFrame:
    weavehr_keys = weavehr.select(["stay_id", "time"]).unique()
    ref_keys = reference.select(["stay_id", "time"]).unique()
    n_weavehr = weavehr_keys.select(pl.len()).collect().item()
    n_ref = ref_keys.select(pl.len()).collect().item()
    n_inner = (
        weavehr_keys.join(ref_keys, on=["stay_id", "time"], how="inner")
        .select(pl.len())
        .collect()
        .item()
    )
    n_only_weavehr = (
        weavehr_keys.join(ref_keys, on=["stay_id", "time"], how="anti")
        .select(pl.len())
        .collect()
        .item()
    )
    n_only_ref = (
        ref_keys.join(weavehr_keys, on=["stay_id", "time"], how="anti")
        .select(pl.len())
        .collect()
        .item()
    )
    return pl.DataFrame(
        {
            "n_weavehr_keys": [n_weavehr],
            "n_reference_keys": [n_ref],
            "n_common_keys": [n_inner],
            "n_only_weavehr_keys": [n_only_weavehr],
            "n_only_reference_keys": [n_only_ref],
        }
    )


def stay_overlap_report(weavehr: pl.LazyFrame, reference: pl.LazyFrame) -> pl.DataFrame:
    weavehr_stays = weavehr.select("stay_id").unique()
    ref_stays = reference.select("stay_id").unique()
    return pl.DataFrame(
        {
            "n_weavehr_stays": [weavehr_stays.select(pl.len()).collect().item()],
            "n_reference_stays": [ref_stays.select(pl.len()).collect().item()],
            "n_common_stays": [
                weavehr_stays.join(ref_stays, on="stay_id", how="inner")
                .select(pl.len())
                .collect()
                .item()
            ],
            "n_only_weavehr_stays": [
                weavehr_stays.join(ref_stays, on="stay_id", how="anti")
                .select(pl.len())
                .collect()
                .item()
            ],
            "n_only_reference_stays": [
                ref_stays.join(weavehr_stays, on="stay_id", how="anti")
                .select(pl.len())
                .collect()
                .item()
            ],
        }
    )


def coverage_report(
    weavehr: pl.LazyFrame, reference: pl.LazyFrame, dynamic_vars: list[str] | None = None
) -> pl.DataFrame:
    vars_ = dynamic_vars or DYNAMIC_VARS
    weavehr_cols = set(weavehr.collect_schema().names())
    ref_cols = set(reference.collect_schema().names())
    rows: list[dict[str, object]] = []
    for c in vars_:
        if c not in weavehr_cols or c not in ref_cols:
            continue
        weavehr_non_null = weavehr.select(pl.col(c).is_not_null().sum()).collect().item()
        ref_non_null = reference.select(pl.col(c).is_not_null().sum()).collect().item()
        rows.append(
            {
                "concept": c,
                "weavehr_non_null": int(weavehr_non_null),
                "reference_non_null": int(ref_non_null),
                "diff_non_null": int(weavehr_non_null) - int(ref_non_null),
            }
        )
    return pl.DataFrame(rows).sort("concept") if rows else pl.DataFrame()


def joined_on_common_keys(
    weavehr: pl.LazyFrame, reference: pl.LazyFrame, dynamic_vars: list[str] | None = None
) -> pl.LazyFrame:
    vars_ = dynamic_vars or DYNAMIC_VARS
    weavehr_cols = set(weavehr.collect_schema().names())
    ref_cols = set(reference.collect_schema().names())
    vars_ = [c for c in vars_ if c in weavehr_cols and c in ref_cols]
    return weavehr.select(["stay_id", "time"] + vars_).join(
        reference.select(["stay_id", "time"] + vars_),
        on=["stay_id", "time"],
        how="inner",
        suffix="_ref",
    )


def missingness_report(
    weavehr: pl.LazyFrame, reference: pl.LazyFrame, dynamic_vars: list[str] | None = None
) -> pl.DataFrame:
    vars_ = dynamic_vars or DYNAMIC_VARS
    joined = joined_on_common_keys(weavehr, reference, vars_)
    cols = joined.collect_schema().names()
    rows: list[pl.DataFrame] = []
    for c in vars_:
        if c not in cols or f"{c}_ref" not in cols:
            continue
        rows.append(
            joined.select(
                [
                    pl.lit(c).alias("concept"),
                    (pl.col(c).is_not_null() & pl.col(f"{c}_ref").is_not_null())
                    .sum()
                    .alias("both_non_null"),
                    (pl.col(c).is_not_null() & pl.col(f"{c}_ref").is_null())
                    .sum()
                    .alias("only_weavehr"),
                    (pl.col(c).is_null() & pl.col(f"{c}_ref").is_not_null())
                    .sum()
                    .alias("only_reference"),
                    (pl.col(c).is_null() & pl.col(f"{c}_ref").is_null()).sum().alias("both_null"),
                ]
            ).collect()
        )
    return pl.concat(rows, how="vertical").sort("concept") if rows else pl.DataFrame()


def value_diff_report(
    weavehr: pl.LazyFrame, reference: pl.LazyFrame, dynamic_vars: list[str] | None = None
) -> pl.DataFrame:
    vars_ = dynamic_vars or DYNAMIC_VARS
    joined = joined_on_common_keys(weavehr, reference, vars_)
    cols = joined.collect_schema().names()
    rows: list[pl.DataFrame] = []
    for c in vars_:
        if c not in cols or f"{c}_ref" not in cols:
            continue
        diff = (pl.col(c) - pl.col(f"{c}_ref")).abs()
        rows.append(
            joined.filter(pl.col(c).is_not_null() & pl.col(f"{c}_ref").is_not_null())
            .select(
                [
                    pl.lit(c).alias("concept"),
                    pl.len().alias("n_both_non_null"),
                    diff.mean().alias("mean_abs_diff"),
                    diff.median().alias("median_abs_diff"),
                    diff.max().alias("max_abs_diff"),
                    (diff / pl.col(f"{c}_ref").abs())
                    .filter(pl.col(f"{c}_ref") != 0)
                    .mean()
                    .alias("mean_rel_diff"),
                ]
            )
            .collect()
        )
    return pl.concat(rows, how="vertical").sort("concept") if rows else pl.DataFrame()


def worst_examples(
    weavehr: pl.LazyFrame, reference: pl.LazyFrame, concept: str, n: int = 20
) -> pl.DataFrame:
    joined = joined_on_common_keys(weavehr, reference, [concept])
    ref_col = f"{concept}_ref"
    return (
        joined.filter(pl.col(concept).is_not_null() & pl.col(ref_col).is_not_null())
        .with_columns((pl.col(concept) - pl.col(ref_col)).abs().alias("abs_diff"))
        .select(
            [
                "stay_id",
                "time",
                pl.col(concept).alias("weavehr_value"),
                pl.col(ref_col).alias("reference_value"),
                "abs_diff",
            ]
        )
        .sort("abs_diff", descending=True)
        .limit(n)
        .collect()
    )


def to_long_non_null(
    df: pl.LazyFrame, dynamic_vars: list[str] | None = None, value_name: str = "value"
) -> pl.LazyFrame:
    vars_ = dynamic_vars or DYNAMIC_VARS
    cols = set(df.collect_schema().names())
    present = [c for c in vars_ if c in cols]
    return (
        df.select(["stay_id", "time"] + present)
        .unpivot(
            index=["stay_id", "time"], on=present, variable_name="concept", value_name=value_name
        )
        .filter(pl.col(value_name).is_not_null())
    )


def reference_only_values(
    weavehr: pl.LazyFrame, reference: pl.LazyFrame, dynamic_vars: list[str] | None = None
) -> pl.LazyFrame:
    weavehr_long = to_long_non_null(weavehr, dynamic_vars, value_name="weavehr_value")
    ref_long = to_long_non_null(reference, dynamic_vars, value_name="reference_value")
    return ref_long.join(
        weavehr_long.select(["stay_id", "time", "concept"]),
        on=["stay_id", "time", "concept"],
        how="anti",
    )


def weavehr_only_values(
    weavehr: pl.LazyFrame, reference: pl.LazyFrame, dynamic_vars: list[str] | None = None
) -> pl.LazyFrame:
    weavehr_long = to_long_non_null(weavehr, dynamic_vars, value_name="weavehr_value")
    ref_long = to_long_non_null(reference, dynamic_vars, value_name="reference_value")
    return weavehr_long.join(
        ref_long.select(["stay_id", "time", "concept"]),
        on=["stay_id", "time", "concept"],
        how="anti",
    )


def per_stay_reproduction_report(
    weavehr: pl.LazyFrame,
    reference: pl.LazyFrame,
    dynamic_vars: list[str] | None = None,
) -> pl.DataFrame:
    """Compare row counts and exact wide-row content for every stay.

    Exact content equality is evaluated after the workflow has normalized both
    tables to the same column order and dtypes. Nulls at the same position are
    treated as equal. A stay is ``content_identical`` only when it exists in
    both tables, has the same ``(stay_id, time)`` keys, and every dynamic value
    on those keys is equal.
    """
    vars_ = dynamic_vars or DYNAMIC_VARS
    weavehr_cols = set(weavehr.collect_schema().names())
    ref_cols = set(reference.collect_schema().names())
    common_vars = [c for c in vars_ if c in weavehr_cols and c in ref_cols]

    weavehr_counts = weavehr.group_by("stay_id").agg(pl.len().alias("n_rows_weavehr"))
    ref_counts = reference.group_by("stay_id").agg(pl.len().alias("n_rows_reference"))

    weavehr_keys = weavehr.select(["stay_id", "time"]).unique()
    ref_keys = reference.select(["stay_id", "time"]).unique()
    only_weavehr = (
        weavehr_keys.join(ref_keys, on=["stay_id", "time"], how="anti")
        .group_by("stay_id")
        .agg(pl.len().alias("n_only_weavehr_rows"))
    )
    only_ref = (
        ref_keys.join(weavehr_keys, on=["stay_id", "time"], how="anti")
        .group_by("stay_id")
        .agg(pl.len().alias("n_only_reference_rows"))
    )

    joined = joined_on_common_keys(weavehr, reference, common_vars)
    if common_vars:
        row_equal = pl.all_horizontal(
            [pl.col(c).eq_missing(pl.col(f"{c}_ref")) for c in common_vars]
        )
    else:
        row_equal = pl.lit(True)
    common_stats = (
        joined.with_columns(row_equal.alias("row_content_equal"))
        .group_by("stay_id")
        .agg(
            [
                pl.len().alias("n_common_rows"),
                pl.col("row_content_equal").sum().alias("n_equal_rows"),
                (~pl.col("row_content_equal")).sum().alias("n_value_mismatch_rows"),
            ]
        )
    )

    report = (
        weavehr_counts.join(ref_counts, on="stay_id", how="full", coalesce=True)
        .join(only_weavehr, on="stay_id", how="left")
        .join(only_ref, on="stay_id", how="left")
        .join(common_stats, on="stay_id", how="left")
        .with_columns(
            [
                pl.col("n_rows_weavehr").fill_null(0),
                pl.col("n_rows_reference").fill_null(0),
                pl.col("n_only_weavehr_rows").fill_null(0),
                pl.col("n_only_reference_rows").fill_null(0),
                pl.col("n_common_rows").fill_null(0),
                pl.col("n_equal_rows").fill_null(0),
                pl.col("n_value_mismatch_rows").fill_null(0),
            ]
        )
        .with_columns(
            [
                ((pl.col("n_rows_weavehr") > 0) & (pl.col("n_rows_reference") > 0)).alias(
                    "in_both"
                ),
                (pl.col("n_rows_weavehr") - pl.col("n_rows_reference")).alias("row_count_diff"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("n_rows_reference") > 0)
                .then(pl.col("row_count_diff") / pl.col("n_rows_reference"))
                .otherwise(None)
                .alias("row_count_relative_error"),
                pl.when(pl.col("n_rows_reference") > 0)
                .then(pl.col("row_count_diff").abs() / pl.col("n_rows_reference"))
                .otherwise(None)
                .alias("row_count_absolute_relative_error"),
                (
                    pl.col("in_both")
                    & (pl.col("n_only_weavehr_rows") == 0)
                    & (pl.col("n_only_reference_rows") == 0)
                    & (pl.col("n_value_mismatch_rows") == 0)
                ).alias("content_identical"),
            ]
        )
        .sort("stay_id")
        .collect()
    )
    return report


def reproduction_accuracy_summary(per_stay: pl.DataFrame) -> pl.DataFrame:
    """Aggregate requested signed errors and complementary absolute metrics."""
    common = per_stay.filter(pl.col("in_both"))

    n_weavehr_stays = per_stay.filter(pl.col("n_rows_weavehr") > 0).height
    n_ref_stays = per_stay.filter(pl.col("n_rows_reference") > 0).height
    n_common_stays = common.height
    n_identical_stays = common.filter(pl.col("content_identical")).height

    total_weavehr_rows = int(per_stay["n_rows_weavehr"].sum() or 0)
    total_ref_rows = int(per_stay["n_rows_reference"].sum() or 0)
    common_weavehr_rows = int(common["n_rows_weavehr"].sum() or 0)
    common_ref_rows = int(common["n_rows_reference"].sum() or 0)

    only_weavehr_rows = int(per_stay["n_only_weavehr_rows"].sum() or 0)
    only_ref_rows = int(per_stay["n_only_reference_rows"].sum() or 0)
    common_rows = int(per_stay["n_common_rows"].sum() or 0)
    equal_rows = int(per_stay["n_equal_rows"].sum() or 0)
    mismatch_rows = int(per_stay["n_value_mismatch_rows"].sum() or 0)
    union_rows = common_rows + only_weavehr_rows + only_ref_rows

    def ratio(numerator: int | float, denominator: int | float) -> float | None:
        return float(numerator / denominator) if denominator else None

    common_rel = common["row_count_relative_error"].drop_nulls()
    common_abs_rel = common["row_count_absolute_relative_error"].drop_nulls()

    return pl.DataFrame(
        {
            "n_stays_weavehr": [n_weavehr_stays],
            "n_stays_reference": [n_ref_stays],
            "n_stays_common": [n_common_stays],
            "n_stays_only_weavehr": [n_weavehr_stays - n_common_stays],
            "n_stays_only_reference": [n_ref_stays - n_common_stays],
            "n_common_stays_identical": [n_identical_stays],
            "n_common_stays_not_identical": [n_common_stays - n_identical_stays],
            "common_stay_exact_match_rate": [ratio(n_identical_stays, n_common_stays)],
            "stay_count_error": [ratio(n_weavehr_stays - n_ref_stays, n_ref_stays)],
            "stay_count_absolute_error": [ratio(abs(n_weavehr_stays - n_ref_stays), n_ref_stays)],
            "mean_common_stay_row_count_error": [common_rel.mean()],
            "mean_common_stay_absolute_row_count_error": [common_abs_rel.mean()],
            "summed_common_stay_row_count_error": [
                ratio(common_weavehr_rows - common_ref_rows, common_ref_rows)
            ],
            "summed_common_stay_absolute_row_count_error": [
                ratio(int(common["row_count_diff"].abs().sum() or 0), common_ref_rows)
            ],
            "total_row_count_error": [ratio(total_weavehr_rows - total_ref_rows, total_ref_rows)],
            "total_absolute_row_count_error": [
                ratio(int(per_stay["row_count_diff"].abs().sum() or 0), total_ref_rows)
            ],
            "n_rows_weavehr": [total_weavehr_rows],
            "n_rows_reference": [total_ref_rows],
            "n_rows_common_keys": [common_rows],
            "n_rows_only_weavehr": [only_weavehr_rows],
            "n_rows_only_reference": [only_ref_rows],
            "n_rows_equal_content": [equal_rows],
            "n_rows_value_mismatch": [mismatch_rows],
            "row_content_disagreement_rate": [
                ratio(only_weavehr_rows + only_ref_rows + mismatch_rows, union_rows)
            ],
        }
    )


def write_reports(
    *,
    weavehr_path: str | Path,
    reference_path: str | Path,
    output_dir: str | Path,
    dynamic_vars: list[str] | None = None,
) -> None:
    """Write standard CSV comparison reports."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    weavehr = scan_dyn(weavehr_path)
    reference = scan_dyn(reference_path)
    pl.concat([table_summary(weavehr, "weavehr"), table_summary(reference, "reference")]).write_csv(
        out / "table_summary.csv"
    )
    key_overlap_report(weavehr, reference).write_csv(out / "key_overlap.csv")
    stay_overlap_report(weavehr, reference).write_csv(out / "stay_overlap.csv")
    coverage_report(weavehr, reference, dynamic_vars).write_csv(out / "coverage.csv")
    missingness_report(weavehr, reference, dynamic_vars).write_csv(out / "missingness.csv")
    value_diff_report(weavehr, reference, dynamic_vars).write_csv(out / "value_diff.csv")
