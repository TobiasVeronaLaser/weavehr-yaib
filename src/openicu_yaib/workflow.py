"""Notebook-friendly workflows for OpenICU -> YAIB wide export and R/RICU comparison.

The functions in this module keep the example notebooks small. They are built
from the original archive notebooks:

* ``01_openicu_to_yaib_dyn*.ipynb`` for wide-table creation
* ``00_main.ipynb`` for window alignment and R/RICU comparison
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from .compare import (
    coverage_report,
    key_overlap_report,
    missingness_report,
    per_stay_reproduction_report,
    reproduction_accuracy_summary,
    scan_dyn,
    stay_overlap_report,
    table_summary,
    value_diff_report,
)
from .concepts import DYNAMIC_VARS, RICU_TO_OPENICU
from .stays import dataset_stay_spec, find_dataset_stay_file
from .transform import build_dynamic_table


@dataclass(frozen=True)
class WideExportResult:
    """Result metadata for an OpenICU -> YAIB wide export."""

    output_path: Path
    summary: pl.DataFrame


@dataclass(frozen=True)
class RICUComparisonResult:
    """Result tables for comparing OpenICU wide output against R/RICU parquet."""

    openicu_path: Path
    reference_path: Path
    reports_dir: Path | None
    table_summary: pl.DataFrame
    stay_overlap: pl.DataFrame
    key_overlap: pl.DataFrame
    window_summary: pl.DataFrame
    window_differences: pl.DataFrame
    coverage: pl.DataFrame
    missingness: pl.DataFrame
    value_diff: pl.DataFrame
    per_stay_reproduction: pl.DataFrame
    reproduction_accuracy: pl.DataFrame

    def as_dict(self) -> dict[str, pl.DataFrame]:
        """Return all report tables as a dictionary for notebook display."""
        return {
            "table_summary": self.table_summary,
            "stay_overlap": self.stay_overlap,
            "key_overlap": self.key_overlap,
            "window_summary": self.window_summary,
            "window_differences": self.window_differences,
            "coverage": self.coverage,
            "missingness": self.missingness,
            "value_diff": self.value_diff,
            "per_stay_reproduction": self.per_stay_reproduction,
            "reproduction_accuracy": self.reproduction_accuracy,
        }


@dataclass(frozen=True)
class DatasetPaths:
    """Default file locations used by the notebook-friendly dataset workflows."""

    dataset: str
    output_root: Path
    concept_root: Path
    icustays_csv: Path | None
    ricu_concept_dict: Path
    ricu_dynamic_path: Path
    ricu_stay_windows_path: Path


def dataset_ricu_code(dataset: str) -> str:
    """Return the short RICU dataset code used in exported file names."""
    mapping = {
        "mimic-iv": "miiv",
        "miiv": "miiv",
        "mimic": "mimic",
        "mimic-iii": "mimic",
        "mimic-iii-demo": "mimic_demo",
        "eicu": "eicu",
        "eicu-crd": "eicu",
        "hirid": "hirid",
        "aumc": "aumc",
        "mimic_demo": "mimic_demo",
        "mimic-demo": "mimic_demo",
        "eicu_demo": "eicu_demo",
        "eicu-demo": "eicu_demo",
        "sic": "sic",
        "sicdb": "sic",
    }
    key = dataset.lower()
    if key not in mapping:
        raise ValueError(
            f"Unsupported dataset {dataset!r}. Add its RICU short code to dataset_ricu_code()."
        )
    return mapping[key]


def _env_path(name: str) -> Path | None:
    """Return an expanded path from an environment variable if it is set."""
    value = os.getenv(name)
    return _as_path(value) if value else None


def _default_output_root() -> Path:
    return _env_path("OPENICU_YAIB_OUTPUT_ROOT") or (Path.home() / "output" / "openicu_yaib")


def _default_concept_root() -> Path:
    raise ValueError(
        "OpenICU concept root is not configured. "
        "Set the concept root explicitly."
    )


def _default_ricu_concept_dict() -> Path:
    return _env_path("OPENICU_YAIB_RICU_CONCEPT_DICT") or (
        Path.home() / "workspace" / "ricu" / "inst" / "extdata" / "config" / "concept-dict.json"
    )


def _default_icustays_csv(dataset: str) -> Path | None:
    env_path = _env_path("OPENICU_YAIB_ICUSTAYS_CSV")
    if env_path is not None:
        return env_path
    return find_dataset_stay_file(dataset)


def default_dataset_paths(
    *,
    dataset: str = "mimic-iv",
    output_root: str | Path | None = None,
    concept_root: str | Path | None = None,
    icustays_csv: str | Path | None = None,
    ricu_concept_dict: str | Path | None = None,
) -> DatasetPaths:
    """Resolve default paths for the simple example notebook.

    Defaults are intentionally user-neutral and can be overridden either by
    function arguments or by environment variables:

    - ``OPENICU_YAIB_OUTPUT_ROOT``
    - ``OPENICU_YAIB_ICUSTAYS_CSV``
    - ``OPENICU_YAIB_RICU_CONCEPT_DICT``

    Output and RICU paths may use the documented environment-variable defaults.
    The OpenICU concept root must be supplied explicitly.
    """
    dataset = dataset.lower()
    out = _as_path(output_root) if output_root is not None else _default_output_root()
    concept = _as_path(concept_root) if concept_root is not None else _default_concept_root()
    ricu_dict = (
        _as_path(ricu_concept_dict)
        if ricu_concept_dict is not None
        else _default_ricu_concept_dict()
    )
    icustays = (
        _as_path(icustays_csv) if icustays_csv is not None else _default_icustays_csv(dataset)
    )

    ricu_code = dataset_ricu_code(dataset)
    return DatasetPaths(
        dataset=dataset,
        output_root=out,
        concept_root=concept,
        icustays_csv=_as_path(icustays) if icustays is not None else None,
        ricu_concept_dict=ricu_dict,
        ricu_dynamic_path=out / f"ricu_dynamic_vars_{ricu_code}.parquet",
        ricu_stay_windows_path=out / f"ricu_stay_windows_{ricu_code}.parquet",
    )


def openicu_wide_output_path(
    *,
    output_root: str | Path,
    max_hours: int | None,
) -> Path:
    """Return the standard OpenICU YAIB-wide output path for a time horizon."""
    out = _as_path(output_root)
    name = "openicu_dyn_all.parquet" if max_hours is None else f"openicu_dyn_{max_hours}h.parquet"
    return out / name


def comparison_reports_dir(
    *,
    output_root: str | Path,
    max_hours: int | None,
) -> Path:
    """Return the standard reports directory for a time horizon."""
    label = "all_hours" if max_hours is None else f"{max_hours}h"
    return _as_path(output_root) / "reports" / label


def _as_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def build_and_write_yaib_wide(
    *,
    concept_root: str | Path,
    icustays_csv: str | Path | None,
    stay_spec=None,
    ricu_concept_dict: str | Path,
    output_path: str | Path,
    dataset: str = "mimic-iv",
    version: str | None = "1.0.0",
    dynamic_vars: list[str] | None = None,
    concept_mapping: dict[str, str] | None = None,
    max_hours: int | None = 168,
    aggregation_mode: str = "ricu",
    grid_end_rounding: str = "floor",
    missing_concepts: str = "warn",
    filter_to_icu_window: bool = True,
    include_grid: bool | None = None,
) -> WideExportResult:
    """Build and write YAIB/RICU-style dynamic wide parquet from OpenICU concepts.

    This is the cleaned-up version of the archive notebooks
    ``01_openicu_to_yaib_dyn.ipynb`` and ``01_openicu_to_yaib_dyn_all.ipynb``.
    Use ``max_hours=None`` to export all available ICU stay hours. Use
    ``max_hours=168`` for the original 7-day mortality setup.
    """
    out = _as_path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    resolved_icustays = _as_path(icustays_csv) if icustays_csv is not None else None
    use_grid = resolved_icustays is not None if include_grid is None else include_grid

    lf = build_dynamic_table(
        concept_root=_as_path(concept_root),
        icustays_csv=resolved_icustays,
        stay_spec=stay_spec,
        ricu_concept_dict=_as_path(ricu_concept_dict),
        dataset=dataset,
        version=version,
        dynamic_vars=dynamic_vars or DYNAMIC_VARS,
        concept_mapping=concept_mapping or RICU_TO_OPENICU,
        aggregation_mode=aggregation_mode,  # type: ignore[arg-type]
        include_grid=use_grid,
        max_hours=max_hours,
        grid_end_rounding=grid_end_rounding,  # type: ignore[arg-type]
        filter_to_icu_window=filter_to_icu_window,
        missing_concepts=missing_concepts,  # type: ignore[arg-type]
    )
    lf.sink_parquet(out)

    summary = (
        scan_dyn(out)
        .select(
            [
                pl.len().alias("n_rows"),
                pl.col("stay_id").n_unique().alias("n_stays"),
                pl.col("time").min().alias("min_time"),
                pl.col("time").max().alias("max_time"),
            ]
        )
        .collect()
    )
    return WideExportResult(output_path=out, summary=summary)


def build_and_write_yaib_wide_for_dataset(
    *,
    dataset: str = "mimic-iv",
    max_hours: int | None = 168,
    output_root: str | Path | None = None,
    concept_root: str | Path | None = None,
    icustays_csv: str | Path | None = None,
    ricu_concept_dict: str | Path | None = None,
    version: str | None = "1.0.0",
    dynamic_vars: list[str] | None = None,
    concept_mapping: dict[str, str] | None = None,
    aggregation_mode: str = "ricu",
    grid_end_rounding: str = "floor",
    missing_concepts: str = "warn",
    filter_to_icu_window: bool = True,
    include_grid: bool | None = None,
    output_path: str | Path | None = None,
) -> WideExportResult:
    """Build and write the standard OpenICU YAIB-wide parquet for a dataset.

    This convenience wrapper is what the simple notebook uses. It resolves the
    usual paths and writes either ``openicu_dyn_all.parquet`` for
    ``max_hours=None`` or ``openicu_dyn_<N>h.parquet`` for a bounded horizon.
    """
    paths = default_dataset_paths(
        dataset=dataset,
        output_root=output_root,
        concept_root=concept_root,
        icustays_csv=icustays_csv,
        ricu_concept_dict=ricu_concept_dict,
    )
    out = (
        _as_path(output_path)
        if output_path is not None
        else openicu_wide_output_path(
            output_root=paths.output_root,
            max_hours=max_hours,
        )
    )
    spec = dataset_stay_spec(dataset)
    return build_and_write_yaib_wide(
        concept_root=paths.concept_root,
        icustays_csv=paths.icustays_csv,
        stay_spec=spec,
        ricu_concept_dict=paths.ricu_concept_dict,
        output_path=out,
        dataset=paths.dataset,
        version=version,
        dynamic_vars=dynamic_vars,
        concept_mapping=concept_mapping,
        max_hours=max_hours,
        aggregation_mode=aggregation_mode,
        grid_end_rounding=grid_end_rounding,
        missing_concepts=missing_concepts,
        filter_to_icu_window=filter_to_icu_window,
        include_grid=include_grid,
    )


def stay_windows_from_wide(df: pl.DataFrame | pl.LazyFrame, *, prefix: str) -> pl.DataFrame:
    """Compute per-stay start/end/n_timepoints from a YAIB wide table."""
    lf = df.lazy() if isinstance(df, pl.DataFrame) else df
    return (
        lf.group_by("stay_id")
        .agg(
            [
                pl.col("time").min().alias(f"{prefix}_start"),
                pl.col("time").max().alias(f"{prefix}_end"),
                pl.col("time").n_unique().alias(f"{prefix}_n_timepoints"),
            ]
        )
        .with_columns(
            (pl.col(f"{prefix}_end") - pl.col(f"{prefix}_start") + 1).alias(
                f"{prefix}_expected_n_timepoints"
            )
        )
        .with_columns(
            (pl.col(f"{prefix}_n_timepoints") - pl.col(f"{prefix}_expected_n_timepoints")).alias(
                f"{prefix}_missing_grid_points"
            )
        )
        .sort("stay_id")
        .collect()
    )


def _numeric_series_to_hours(series: pl.Series) -> pl.Series:
    values = series.cast(pl.Float64)
    max_abs = values.abs().max()
    # R exports can arrive either as hours or as milliseconds. Values larger
    # than one year in hours are treated as milliseconds.
    if max_abs is not None and max_abs > 24 * 366:
        values = values / 3_600_000
    return values.round(0).cast(pl.Int64)


def _series_to_hours(series: pl.Series) -> pl.Series:
    if series.dtype == pl.Duration:
        return (series.dt.total_seconds() / 3600).round(0).cast(pl.Int64)
    if series.dtype.is_numeric():
        return _numeric_series_to_hours(series)
    # Last fallback for string-like exports. Polars will fail loudly if the
    # values are not numeric, which is better than silently comparing nonsense.
    return _numeric_series_to_hours(series.cast(pl.Float64))


def _normalize_ricu_stay_id(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize dataset-specific RICU ICU-stay identifiers to ``stay_id``."""
    if "stay_id" in df.columns:
        return df

    lookup = {name.lower(): name for name in df.columns}
    for candidate in (
        "patientunitstayid",  # eICU
        "icustay_id",  # MIMIC-III
        "icustayid",
        "admissionid",  # AUMC
        "patientid",  # HiRID
        "caseid",  # SICdb
    ):
        if candidate in lookup:
            return df.rename({lookup[candidate]: "stay_id"})

    raise ValueError(f"Could not identify RICU stay ID column; available columns: {df.columns}")


def read_ricu_stay_windows(path: str | Path, *, max_hours: int | None = 168) -> pl.DataFrame:
    """Read R/RICU stay windows and normalize start/end to integer hours.

    The archive notebooks used both R duration columns and millisecond columns.
    This helper accepts both forms and caps ``end`` to ``max_hours`` when given.
    """
    windows = _normalize_ricu_stay_id(pl.read_parquet(_as_path(path)))
    required = {"stay_id", "start", "end"}
    missing = required - set(windows.columns)
    if missing:
        raise ValueError(f"RICU stay-windows parquet is missing columns: {sorted(missing)}")

    windows = windows.with_columns(
        [
            pl.col("stay_id").cast(pl.Int64),
            _series_to_hours(windows["start"]).alias("ricu_start"),
            _series_to_hours(windows["end"]).alias("ricu_end"),
        ]
    ).select(["stay_id", "ricu_start", "ricu_end"])

    if max_hours is not None:
        windows = windows.with_columns(
            pl.col("ricu_end").clip(upper_bound=max_hours).alias("ricu_end")
        )

    return windows.with_columns(
        (pl.col("ricu_end") - pl.col("ricu_start") + 1).alias("ricu_expected_n_timepoints")
    ).sort("stay_id")


def normalize_ricu_dynamic_reference(
    *,
    reference_dynamic_path: str | Path,
    ricu_windows: pl.DataFrame,
    openicu_columns: list[str],
) -> pl.DataFrame:
    """Load R/RICU dynamic vars and apply the same window filtering as 00_main."""
    reference = _normalize_ricu_stay_id(pl.read_parquet(_as_path(reference_dynamic_path)))

    if "time" not in reference.columns:
        lookup = {name.lower(): name for name in reference.columns}
        if "labresultoffset" in lookup:
            source_time = lookup["labresultoffset"]
            reference = reference.with_columns(
                _series_to_hours(reference[source_time]).alias("time")
            )
        else:
            raise ValueError(
                "Could not identify RICU dynamic time column; "
                f"available columns: {reference.columns}"
            )

    reference = reference.with_columns(
        [
            pl.col("stay_id").cast(pl.Int64),
            pl.col("time").cast(pl.Int64),
        ]
    )

    selected_columns = [c for c in openicu_columns if c in reference.columns]
    if "stay_id" not in selected_columns or "time" not in selected_columns:
        raise ValueError("Reference dynamic parquet must contain stay_id and time columns.")

    return (
        reference.select(selected_columns)
        .join(ricu_windows, on="stay_id", how="inner")
        .filter((pl.col("time") >= pl.col("ricu_start")) & (pl.col("time") <= pl.col("ricu_end")))
        .select(selected_columns)
    )


def normalize_wide_dtypes_for_comparison(
    df: pl.DataFrame,
    *,
    columns: list[str] | None = None,
    dynamic_vars: list[str] | None = None,
    value_dtype: pl.DataType = pl.Float32,
) -> pl.DataFrame:
    """Cast a YAIB-wide table to stable comparison dtypes.

    R/RICU and Python/Polars may read parquet columns with slightly different
    physical types. The comparison is intended to operate on YAIB-style data:
    ``stay_id`` and ``time`` as integer hours, dynamic variables as the same
    numeric dtype, and identical column order.
    """
    target_columns = columns or df.columns
    vars_ = dynamic_vars or [c for c in target_columns if c not in {"stay_id", "time"}]
    present_vars = [c for c in vars_ if c in df.columns]
    selected = [c for c in target_columns if c in df.columns]
    return df.with_columns(
        [
            pl.col("stay_id").cast(pl.Int64),
            pl.col("time").cast(pl.Int64),
            *[pl.col(c).cast(value_dtype, strict=False).alias(c) for c in present_vars],
        ]
    ).select(selected)


def compare_openicu_wide_to_ricu(
    *,
    openicu_wide_path: str | Path,
    ricu_dynamic_path: str | Path,
    ricu_stay_windows_path: str | Path,
    reports_dir: str | Path | None = None,
    max_hours: int | None = 168,
    dynamic_vars: list[str] | None = None,
    write_normalized_reference: bool = True,
) -> RICUComparisonResult:
    """Compare OpenICU YAIB wide parquet against R/RICU dynamic vars parquet.

    This is the cleaned-up version of the original archive ``00_main.ipynb``:
    it aligns RICU stay windows, caps them to ``max_hours`` when requested,
    filters the RICU dynamic table to these windows, then computes overlap,
    coverage, missingness and numeric difference reports.
    """
    vars_ = dynamic_vars or DYNAMIC_VARS
    openicu_path = _as_path(openicu_wide_path)
    reference_path = _as_path(ricu_dynamic_path)
    out_dir = _as_path(reports_dir) if reports_dir is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    openicu = pl.read_parquet(openicu_path)
    openicu = normalize_wide_dtypes_for_comparison(openicu, dynamic_vars=vars_)
    if max_hours is not None:
        openicu = openicu.filter(pl.col("time") <= max_hours)

    openicu_windows = stay_windows_from_wide(openicu, prefix="openicu")

    ricu_windows = read_ricu_stay_windows(
        ricu_stay_windows_path,
        max_hours=max_hours,
    )

    valid_metric_stays = ricu_windows.filter(pl.col("ricu_end").is_not_null()).select("stay_id")

    reference = normalize_ricu_dynamic_reference(
        reference_dynamic_path=reference_path,
        ricu_windows=ricu_windows,
        openicu_columns=openicu.columns,
    )

    reference = normalize_wide_dtypes_for_comparison(
        reference,
        columns=openicu.columns,
        dynamic_vars=vars_,
    )

    openicu_metric = openicu.join(
        valid_metric_stays,
        on="stay_id",
        how="semi",
    )

    reference_metric = reference.join(
        valid_metric_stays,
        on="stay_id",
        how="semi",
    )

    window_differences = (
        openicu_windows.join(ricu_windows, on="stay_id", how="full", coalesce=True)
        .with_columns(
            [
                (pl.col("openicu_start") - pl.col("ricu_start")).alias("diff_start"),
                (pl.col("openicu_end") - pl.col("ricu_end")).alias("diff_end"),
                (pl.col("openicu_n_timepoints") - pl.col("ricu_expected_n_timepoints")).alias(
                    "diff_n_timepoints"
                ),
            ]
        )
        .filter(
            pl.col("diff_start").is_null()
            | pl.col("diff_end").is_null()
            | (pl.col("diff_start") != 0)
            | (pl.col("diff_end") != 0)
            | (pl.col("diff_n_timepoints") != 0)
        )
        .sort("stay_id")
    )

    joined_windows = openicu_windows.join(ricu_windows, on="stay_id", how="full", coalesce=True)
    window_summary = joined_windows.select(
        [
            pl.len().alias("n_stays_total"),
            pl.col("openicu_start").is_not_null().sum().alias("n_stays_in_openicu"),
            pl.col("ricu_start").is_not_null().sum().alias("n_stays_in_ricu"),
            ((pl.col("openicu_start") - pl.col("ricu_start")) == 0).sum().alias("n_same_start"),
            ((pl.col("openicu_end") - pl.col("ricu_end")) == 0).sum().alias("n_same_end"),
            ((pl.col("openicu_end") - pl.col("ricu_end")) < 0).sum().alias("n_openicu_shorter"),
            ((pl.col("openicu_end") - pl.col("ricu_end")) > 0).sum().alias("n_openicu_longer"),
            (pl.col("openicu_end") - pl.col("ricu_end")).min().alias("min_diff_end"),
            (pl.col("openicu_end") - pl.col("ricu_end")).max().alias("max_diff_end"),
            (pl.col("openicu_end") - pl.col("ricu_end")).mean().alias("mean_diff_end"),
            pl.col("ricu_end").is_null().sum().alias("n_excluded_metric_null_ricu_end"),
        ]
    )

    openicu_lf = openicu_metric.lazy()
    reference_lf = reference_metric.lazy()
    per_stay = per_stay_reproduction_report(openicu_lf, reference_lf, vars_)
    accuracy = reproduction_accuracy_summary(per_stay)
    table = pl.concat(
        [table_summary(openicu_lf, "openicu"), table_summary(reference_lf, "ricu_reference")]
    )
    result = RICUComparisonResult(
        openicu_path=openicu_path,
        reference_path=reference_path,
        reports_dir=out_dir,
        table_summary=table,
        stay_overlap=stay_overlap_report(openicu_lf, reference_lf),
        key_overlap=key_overlap_report(openicu_lf, reference_lf),
        window_summary=window_summary,
        window_differences=window_differences,
        coverage=coverage_report(openicu_lf, reference_lf, vars_),
        missingness=missingness_report(openicu_lf, reference_lf, vars_),
        value_diff=value_diff_report(openicu_lf, reference_lf, vars_),
        per_stay_reproduction=per_stay,
        reproduction_accuracy=accuracy,
    )

    if out_dir is not None:
        result.table_summary.write_csv(out_dir / "table_summary.csv")
        result.stay_overlap.write_csv(out_dir / "stay_overlap.csv")
        result.key_overlap.write_csv(out_dir / "key_overlap.csv")
        result.window_summary.write_csv(out_dir / "window_summary.csv")
        result.window_differences.write_csv(out_dir / "window_differences.csv")
        result.coverage.write_csv(out_dir / "coverage.csv")
        result.missingness.write_csv(out_dir / "missingness.csv")
        result.value_diff.write_csv(out_dir / "value_diff.csv")
        result.per_stay_reproduction.write_csv(out_dir / "per_stay_reproduction.csv")
        result.reproduction_accuracy.write_csv(out_dir / "reproduction_accuracy.csv")
        if write_normalized_reference:
            reference.write_parquet(out_dir / "ricu_reference_normalized.parquet")
            ricu_windows.write_parquet(out_dir / "ricu_windows_normalized.parquet")

    return result


def compare_openicu_wide_to_ricu_for_dataset(
    *,
    dataset: str = "mimic-iv",
    max_hours: int | None = 168,
    output_root: str | Path | None = None,
    concept_root: str | Path | None = None,
    icustays_csv: str | Path | None = None,
    ricu_concept_dict: str | Path | None = None,
    openicu_wide_path: str | Path | None = None,
    ricu_dynamic_path: str | Path | None = None,
    ricu_stay_windows_path: str | Path | None = None,
    reports_dir: str | Path | None = None,
    dynamic_vars: list[str] | None = None,
    write_normalized_reference: bool = True,
) -> RICUComparisonResult:
    """Compare the standard dataset-specific OpenICU and R/RICU parquet files."""
    paths = default_dataset_paths(
        dataset=dataset,
        output_root=output_root,
        concept_root=concept_root,
        icustays_csv=icustays_csv,
        ricu_concept_dict=ricu_concept_dict,
    )
    openicu_path = (
        _as_path(openicu_wide_path)
        if openicu_wide_path is not None
        else openicu_wide_output_path(
            output_root=paths.output_root,
            max_hours=max_hours,
        )
    )
    return compare_openicu_wide_to_ricu(
        openicu_wide_path=openicu_path,
        ricu_dynamic_path=_as_path(ricu_dynamic_path)
        if ricu_dynamic_path is not None
        else paths.ricu_dynamic_path,
        ricu_stay_windows_path=(
            _as_path(ricu_stay_windows_path)
            if ricu_stay_windows_path is not None
            else paths.ricu_stay_windows_path
        ),
        reports_dir=(
            _as_path(reports_dir)
            if reports_dir is not None
            else comparison_reports_dir(output_root=paths.output_root, max_hours=max_hours)
        ),
        max_hours=max_hours,
        dynamic_vars=dynamic_vars,
        write_normalized_reference=write_normalized_reference,
    )


def display_comparison_overview(result: RICUComparisonResult) -> dict[str, pl.DataFrame]:
    """Return the most useful report tables for compact notebook display."""
    return {
        "table_summary": result.table_summary,
        "stay_overlap": result.stay_overlap,
        "key_overlap": result.key_overlap,
        "window_summary": result.window_summary,
        "window_differences_head": result.window_differences.head(20),
        "coverage_by_largest_difference": result.coverage.sort("diff_non_null"),
        "missingness_by_reference_only": result.missingness.sort("only_reference", descending=True),
        "value_diff_by_max_abs_diff": result.value_diff.sort("max_abs_diff", descending=True),
        "reproduction_accuracy": result.reproduction_accuracy,
        "non_identical_common_stays_head": result.per_stay_reproduction.filter(
            pl.col("in_both") & ~pl.col("content_identical")
        ).head(20),
    }
