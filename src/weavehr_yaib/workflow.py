"""Notebook-friendly workflows for WeavEHR -> YAIB wide export and R/RICU comparison.

The functions in this module keep the example notebooks small. They are built
from the original archive notebooks:

* ``archive/01_openicu_to_yaib_dyn*.ipynb`` (pre-WeavEHR rename) for wide-table creation
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
from .concepts import DYNAMIC_VARS, RICU_TO_WEAVEHR
from .io import find_concept_file, require_concept_column
from .stay_ids import (
    RICU_STAY_ID_SPACES,
    StayIdComparison,
    StaySource,
    load_stay_crosswalk,
    stay_id_version_assumption,
    weavehr_stay_id_space,
)
from .stays import SIC_CASE_ID_HINT, SIC_DATASETS, dataset_stay_spec, find_dataset_stay_file
from .transform import build_dynamic_table
from .versions import (
    DatasetVersion,
    VersionComparison,
    read_provenance_field,
    read_weavehr_provenance,
    relationship_from_counts,
    resolve_reference_version,
    resolve_weavehr_version,
    scope_label,
    versions_equal,
    write_weavehr_provenance,
)
from .workspace import weavehr_aumc_stays, weavehr_hirid_stays, weavehr_sic_stays


@dataclass(frozen=True)
class WideExportResult:
    """Result metadata for a WeavEHR -> YAIB wide export."""

    output_path: Path
    summary: pl.DataFrame
    dataset_version: DatasetVersion | None = None


@dataclass(frozen=True)
class RICUComparisonResult:
    """Result tables for comparing WeavEHR wide output against R/RICU parquet."""

    weavehr_path: Path
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
    # Version provenance and comparison scope; see compare_weavehr_wide_to_ricu.
    provenance: pl.DataFrame
    scope_overlap: pl.DataFrame
    scope_differences: pl.DataFrame

    def as_dict(self) -> dict[str, pl.DataFrame]:
        """Return all report tables as a dictionary for notebook display."""
        return {
            "provenance": self.provenance,
            "scope_overlap": self.scope_overlap,
            "scope_differences": self.scope_differences,
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
    return _env_path("WEAVEHR_YAIB_OUTPUT_ROOT") or (Path.home() / "output" / "weavehr_yaib")


def _default_concept_root() -> Path:
    raise ValueError(
        "WeavEHR concept root is not configured. "
        "Set the concept root explicitly."
    )


def _default_ricu_concept_dict() -> Path:
    return _env_path("WEAVEHR_YAIB_RICU_CONCEPT_DICT") or (
        Path.home() / "workspace" / "ricu" / "inst" / "extdata" / "config" / "concept-dict.json"
    )


def _default_icustays_csv(dataset: str) -> Path | None:
    env_path = _env_path("WEAVEHR_YAIB_ICUSTAYS_CSV")
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

    - ``WEAVEHR_YAIB_OUTPUT_ROOT``
    - ``WEAVEHR_YAIB_ICUSTAYS_CSV``
    - ``WEAVEHR_YAIB_RICU_CONCEPT_DICT``

    Output and RICU paths may use the documented environment-variable defaults.
    The WeavEHR concept root must be supplied explicitly.
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


def weavehr_wide_output_path(
    *,
    output_root: str | Path,
    max_hours: int | None,
) -> Path:
    """Return the standard WeavEHR YAIB-wide output path for a time horizon."""
    out = _as_path(output_root)
    name = "weavehr_dyn_all.parquet" if max_hours is None else f"weavehr_dyn_{max_hours}h.parquet"
    return out / name


def comparison_reports_dir(
    *,
    output_root: str | Path,
    max_hours: int | None,
    scope: str | None = None,
) -> Path:
    """Return the standard reports directory for a time horizon.

    ``scope`` (see :func:`~weavehr_yaib.versions.scope_label`) adds a
    subdirectory per compared version pair so pairs do not overwrite each other.
    """
    label = "all_hours" if max_hours is None else f"{max_hours}h"
    out = _as_path(output_root) / "reports" / label
    return out / scope if scope else out


def _as_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def build_and_write_yaib_wide(
    *,
    concept_root: str | Path,
    icustays_csv: str | Path | None,
    stay_spec=None,
    normalized_stays: pl.LazyFrame | None = None,
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
    dataset_version: str | None = None,
) -> WideExportResult:
    """Build and write YAIB/RICU-style dynamic wide parquet from WeavEHR concepts.

    ``dataset_version`` keeps only concept rows of that WeavEHR dataset version
    (requires the ``dataset_version`` concept column to have an effect).

    This is the cleaned-up version of the archive notebooks
    ``01_openicu_to_yaib_dyn.ipynb`` and ``01_openicu_to_yaib_dyn_all.ipynb``.
    Use ``max_hours=None`` to export all available ICU stay hours. Use
    ``max_hours=168`` for the original 7-day mortality setup.
    """
    out = _as_path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    resolved_icustays = _as_path(icustays_csv) if icustays_csv is not None else None
    use_grid = (
        resolved_icustays is not None or normalized_stays is not None
        if include_grid is None
        else include_grid
    )

    lf = build_dynamic_table(
        concept_root=_as_path(concept_root),
        icustays_csv=resolved_icustays,
        stay_spec=stay_spec,
        normalized_stays=normalized_stays,
        ricu_concept_dict=_as_path(ricu_concept_dict),
        dataset=dataset,
        version=version,
        dynamic_vars=dynamic_vars or DYNAMIC_VARS,
        concept_mapping=concept_mapping or RICU_TO_WEAVEHR,
        aggregation_mode=aggregation_mode,  # type: ignore[arg-type]
        include_grid=use_grid,
        max_hours=max_hours,
        grid_end_rounding=grid_end_rounding,  # type: ignore[arg-type]
        filter_to_icu_window=filter_to_icu_window,
        missing_concepts=missing_concepts,  # type: ignore[arg-type]
        dataset_version=dataset_version,
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
    dataset_version: str | None = None,
) -> WideExportResult:
    """Build and write the standard WeavEHR YAIB-wide parquet for a dataset.

    This convenience wrapper is what the simple notebook uses. It resolves the
    usual paths and writes either ``weavehr_dyn_all.parquet`` for
    ``max_hours=None`` or ``weavehr_dyn_<N>h.parquet`` for a bounded horizon.

    ``version`` is the WeavEHR *concept* version; ``dataset_version`` selects
    the WeavEHR *dataset* version. The dataset version is resolved without
    guessing (see :func:`~weavehr_yaib.versions.resolve_weavehr_version`) and
    written to ``<output>.provenance.json`` for the comparison.
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
        else weavehr_wide_output_path(
            output_root=paths.output_root,
            max_hours=max_hours,
        )
    )
    spec = dataset_stay_spec(dataset)

    normalized_stays = None
    resolved_icustays = paths.icustays_csv

    workspace = paths.concept_root.parent
    concept_files = _mapped_concept_files(
        paths.concept_root,
        dataset=paths.dataset,
        version=version,
        dynamic_vars=dynamic_vars or DYNAMIC_VARS,
        concept_mapping=concept_mapping or RICU_TO_WEAVEHR,
    )
    weavehr_version = resolve_weavehr_version(
        dataset=paths.dataset,
        concept_files=concept_files,
        workspace=workspace,
        dataset_version=dataset_version,
    )

    # Without an explicit stay table, HiRID and AUMC stay windows are rebuilt
    # from the WeavEHR extraction events next to the concept directory.
    stay_source: StaySource = "raw_stay_table" if resolved_icustays is not None else "unknown"
    if dataset.lower() == "hirid" and icustays_csv is None:
        normalized_stays = weavehr_hirid_stays(workspace, version=weavehr_version.version)
        resolved_icustays = None
        stay_source = "weavehr_hirid_events"

    if dataset.lower() == "aumc" and icustays_csv is None:
        normalized_stays = weavehr_aumc_stays(workspace, version=weavehr_version.version)
        resolved_icustays = None
        stay_source = "weavehr_visit_events"

    # SIC: one stay per case from the WeavEHR cases events, never PatientID.
    if dataset.lower() in SIC_DATASETS and icustays_csv is None:
        require_concept_column(concept_files, "case_id", SIC_CASE_ID_HINT)
        normalized_stays = weavehr_sic_stays(workspace, version=weavehr_version.version)
        resolved_icustays = None
        stay_source = "weavehr_sic_cases_events"

    result = build_and_write_yaib_wide(
        concept_root=paths.concept_root,
        icustays_csv=resolved_icustays,
        stay_spec=spec,
        normalized_stays=normalized_stays,
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
        dataset_version=weavehr_version.version,
    )
    write_weavehr_provenance(
        result.output_path,
        weavehr_version,
        max_hours=max_hours,
        stay_source=stay_source,
        stay_id_space=weavehr_stay_id_space(paths.dataset, stay_source),
    )
    return WideExportResult(
        output_path=result.output_path, summary=result.summary, dataset_version=weavehr_version
    )


def _mapped_concept_files(
    concept_root: Path,
    *,
    dataset: str,
    version: str | None,
    dynamic_vars: list[str],
    concept_mapping: dict[str, str],
) -> list[Path]:
    """Concept parquets that the dynamic-table build will read."""
    files = []
    for ricu_name in dynamic_vars:
        weavehr_name = concept_mapping.get(ricu_name)
        if weavehr_name is None:
            continue
        path = find_concept_file(concept_root, weavehr_name, dataset=dataset, version=version)
        if path is not None:
            files.append(path)
    return files


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
    weavehr_columns: list[str],
) -> pl.DataFrame:
    """Load R/RICU dynamic vars and apply the same window filtering as 00_main."""
    reference = _normalize_ricu_stay_id(pl.read_parquet(_as_path(reference_dynamic_path)))

    if "time" not in reference.columns:
        lookup = {name.lower(): name for name in reference.columns}
        source_time = None
        for candidate in (
            "labresultoffset",
            "respcarestatusoffset",
            "measuredat",
            "datetime",
        ):
            if candidate in lookup:
                source_time = lookup[candidate]
                break

        if source_time is not None:
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

    selected_columns = [c for c in weavehr_columns if c in reference.columns]
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


def _unknown_versions() -> VersionComparison:
    return VersionComparison(
        weavehr=DatasetVersion("weavehr", None, "unknown"),
        reference=DatasetVersion("reference", None, "unknown"),
    )


def _key_counts(weavehr: pl.DataFrame, reference: pl.DataFrame) -> tuple[int, int, int]:
    w = weavehr.select("stay_id", "time").unique()
    r = reference.select("stay_id", "time").unique()
    return w.height, r.height, w.join(r, on=["stay_id", "time"], how="inner").height


def _scope_tables(
    *,
    versions: VersionComparison,
    stay_ids: StayIdComparison,
    weavehr_stays: set[int],
    reference_stays: set[int],
    unmapped_reference_stays: set[int],
    weavehr_concepts: set[str],
    reference_concepts: set[str],
    key_counts: tuple[int, int, int],
    max_hours: int | None,
    weavehr_path: Path,
    reference_path: Path,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict[str, object]]:
    """Build the provenance, scope-overlap and scope-difference tables.

    Without a common stay identifier space (``stay_ids.matchable`` false) the
    stay and key dimensions are not directly comparable: both stay ID sets are
    listed separately and no shared counts are derived from numeric equality.
    """
    matchable = stay_ids.matchable
    shared_stays = weavehr_stays & reference_stays if matchable else set()
    shared_concepts = weavehr_concepts & reference_concepts
    comparable = matchable and bool(shared_stays) and bool(shared_concepts)
    full = versions.full_scope

    def overlap_row(
        dimension: str, n_w: int, n_r: int, n_s: int, *, matched: bool = True
    ) -> dict[str, object]:
        return {
            "dimension": dimension,
            "n_weavehr": n_w,
            "n_reference": n_r,
            "n_shared": n_s if matched else None,
            "n_weavehr_only": n_w - n_s if matched else None,
            "n_reference_only": n_r - n_s if matched else None,
            "relationship": relationship_from_counts(n_w, n_r, n_s, comparable=matched),
        }

    rows = [
        overlap_row(
            "stays", len(weavehr_stays), len(reference_stays), len(shared_stays), matched=matchable
        ),
        overlap_row(
            "concepts", len(weavehr_concepts), len(reference_concepts), len(shared_concepts)
        ),
        overlap_row("stay_time_keys", *key_counts, matched=matchable),
    ]
    counts = ["n_weavehr", "n_reference", "n_shared", "n_weavehr_only", "n_reference_only"]
    scope_overlap = pl.DataFrame(rows, schema_overrides={c: pl.Int64 for c in counts})

    if matchable:
        differences = [
            ("stay", str(x), "weavehr_only") for x in sorted(weavehr_stays - reference_stays)
        ]
        differences += [
            ("stay", str(x), "reference_only") for x in sorted(reference_stays - weavehr_stays)
        ]
    else:
        # Separate ID sets in different spaces; equal numbers mean nothing.
        differences = [("stay", str(x), "weavehr") for x in sorted(weavehr_stays)]
        differences += [("stay", str(x), "reference") for x in sorted(reference_stays)]
    differences += [
        ("stay", str(x), "reference_without_crosswalk") for x in sorted(unmapped_reference_stays)
    ]
    differences += [
        ("concept", x, "weavehr_only") for x in sorted(weavehr_concepts - reference_concepts)
    ]
    differences += [
        ("concept", x, "reference_only") for x in sorted(reference_concepts - weavehr_concepts)
    ]
    scope_differences = pl.DataFrame(
        differences,
        schema={"dimension": pl.String, "identifier": pl.String, "side": pl.String},
        orient="row",
    )

    version_assumption = stay_id_version_assumption(
        stay_ids.basis, same_verified_version=versions.full_scope
    )
    if not matchable:
        stay_confidence = "not_comparable"
    elif version_assumption == "same_verified_version":
        stay_confidence = "high"
    else:
        # Crosswalks and unverified cross-version stay ID stability: never "high".
        stay_confidence = "medium"
    scope: dict[str, object] = {
        "comparison_scope": "full" if full else "shared_subset",
        "validation_level": versions.validation_level(comparable=comparable),
        "metrics_restricted_to_shared_scope": not full,
        **stay_ids.as_dict(),
        "stay_comparison_confidence": stay_confidence,
        "stay_id_version_assumption": version_assumption,
        "n_scope_shared_stays": len(shared_stays) if matchable else None,
        "n_scope_weavehr_only_stays": len(weavehr_stays - reference_stays) if matchable else None,
        "n_scope_reference_only_stays": (
            len(reference_stays - weavehr_stays) if matchable else None
        ),
        "n_scope_reference_stays_without_crosswalk": len(unmapped_reference_stays),
        "n_scope_shared_concepts": len(shared_concepts),
        "n_scope_weavehr_only_concepts": len(weavehr_concepts - reference_concepts),
        "n_scope_reference_only_concepts": len(reference_concepts - weavehr_concepts),
    }
    provenance = pl.DataFrame(
        [
            {
                **versions.as_dict(),
                **scope,
                "stay_relationship": rows[0]["relationship"],
                "concept_relationship": rows[1]["relationship"],
                "max_hours": max_hours,
                "weavehr_path": str(weavehr_path),
                "reference_path": str(reference_path),
            }
        ],
        schema_overrides={
            "weavehr_dataset_version": pl.String,
            "reference_dataset_version": pl.String,
            "weavehr_representation": pl.String,
            "reference_representation": pl.String,
            "same_version": pl.Boolean,
            "max_hours": pl.Int64,
            "weavehr_stay_id_space": pl.String,
            "reference_stay_id_space": pl.String,
            "n_scope_shared_stays": pl.Int64,
            "n_scope_weavehr_only_stays": pl.Int64,
            "n_scope_reference_only_stays": pl.Int64,
        },
    )
    return provenance, scope_overlap, scope_differences, scope


def compare_weavehr_wide_to_ricu(
    *,
    weavehr_wide_path: str | Path,
    ricu_dynamic_path: str | Path,
    ricu_stay_windows_path: str | Path,
    reports_dir: str | Path | None = None,
    max_hours: int | None = 168,
    dynamic_vars: list[str] | None = None,
    write_normalized_reference: bool = True,
    versions: VersionComparison | None = None,
    stay_ids: StayIdComparison | None = None,
) -> RICUComparisonResult:
    """Compare WeavEHR YAIB wide parquet against R/RICU dynamic vars parquet.

    This is the cleaned-up version of the original archive ``00_main.ipynb``:
    it aligns RICU stay windows, caps them to ``max_hours`` when requested,
    filters the RICU dynamic table to these windows, then computes overlap,
    coverage, missingness and numeric difference reports.

    ``versions`` records which dataset versions are compared. Only verified,
    identical versions (``comparison_scope == "full"``) use the full comparison.
    Otherwise (cross-version, assumed or unknown versions) every numeric report
    describes only the shared stays x shared concepts; WeavEHR-only and
    reference-only stays and concepts are listed in ``scope_differences`` and
    counted in ``scope_overlap`` instead of being scored as errors. The
    ``provenance`` table and the provenance columns added to
    ``reproduction_accuracy`` state the versions, scope and validation level.

    ``stay_ids`` states the stay identifier spaces of both sides (default: read
    from the provenance files). Stays are matched only within a common space or
    through a crosswalk, which translates reference stay IDs into the WeavEHR
    space first. Otherwise no stay-keyed report (windows, keys, metrics) is
    computed and the comparison is ``not_comparable``; provenance and both stay
    ID sets are still reported.
    """
    vars_ = dynamic_vars or DYNAMIC_VARS
    versions = versions or _unknown_versions()
    stay_ids = stay_ids or default_stay_ids(
        weavehr_wide_path=weavehr_wide_path, ricu_dynamic_path=ricu_dynamic_path
    )
    weavehr_path = _as_path(weavehr_wide_path)
    reference_path = _as_path(ricu_dynamic_path)
    out_dir = _as_path(reports_dir) if reports_dir is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    weavehr = pl.read_parquet(weavehr_path)
    weavehr = normalize_wide_dtypes_for_comparison(weavehr, dynamic_vars=vars_)
    if max_hours is not None:
        weavehr = weavehr.filter(pl.col("time") <= max_hours)

    weavehr_windows = stay_windows_from_wide(weavehr, prefix="weavehr")

    ricu_windows = read_ricu_stay_windows(
        ricu_stay_windows_path,
        max_hours=max_hours,
    )

    reference = normalize_ricu_dynamic_reference(
        reference_dynamic_path=reference_path,
        ricu_windows=ricu_windows,
        weavehr_columns=weavehr.columns,
    )

    # With a crosswalk, move the reference into the WeavEHR stay ID space.
    ricu_windows, unmapped_reference_stays = stay_ids.to_weavehr_ids(ricu_windows)
    reference, _ = stay_ids.to_weavehr_ids(reference)

    valid_metric_stays = ricu_windows.filter(pl.col("ricu_end").is_not_null()).select("stay_id")

    reference = normalize_wide_dtypes_for_comparison(
        reference,
        columns=weavehr.columns,
        dynamic_vars=vars_,
    )

    provenance, scope_overlap, scope_differences, scope = _scope_tables(
        versions=versions,
        stay_ids=stay_ids,
        weavehr_stays=set(weavehr["stay_id"].unique().to_list()),
        reference_stays=set(valid_metric_stays["stay_id"].to_list()),
        unmapped_reference_stays=set(unmapped_reference_stays["stay_id"].to_list()),
        weavehr_concepts={c for c in vars_ if c in weavehr.columns},
        reference_concepts={c for c in vars_ if c in pl.read_parquet_schema(reference_path)},
        key_counts=_key_counts(weavehr, reference),
        max_hours=max_hours,
        weavehr_path=weavehr_path,
        reference_path=reference_path,
    )

    if versions.full_scope:
        metric_vars = vars_
        metric_stays = valid_metric_stays
    else:
        shared_concepts = {c for c in vars_ if c in weavehr.columns} & set(
            pl.read_parquet_schema(reference_path)
        )
        metric_vars = [c for c in vars_ if c in shared_concepts]
        metric_stays = valid_metric_stays.join(
            weavehr.select("stay_id").unique(), on="stay_id", how="semi"
        )

    weavehr_metric = weavehr.join(
        metric_stays,
        on="stay_id",
        how="semi",
    )

    reference_metric = reference.join(
        metric_stays,
        on="stay_id",
        how="semi",
    )

    if not versions.full_scope:
        keep = ["stay_id", "time", *metric_vars]
        weavehr_metric = weavehr_metric.select([c for c in keep if c in weavehr_metric.columns])
        reference_metric = reference_metric.select(
            [c for c in keep if c in reference_metric.columns]
        )

    if stay_ids.matchable:
        window_differences = (
            weavehr_windows.join(ricu_windows, on="stay_id", how="full", coalesce=True)
            .with_columns(
                [
                    (pl.col("weavehr_start") - pl.col("ricu_start")).alias("diff_start"),
                    (pl.col("weavehr_end") - pl.col("ricu_end")).alias("diff_end"),
                    (pl.col("weavehr_n_timepoints") - pl.col("ricu_expected_n_timepoints")).alias(
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

        joined_windows = weavehr_windows.join(ricu_windows, on="stay_id", how="full", coalesce=True)
        window_summary = joined_windows.select(
            [
                pl.len().alias("n_stays_total"),
                pl.col("weavehr_start").is_not_null().sum().alias("n_stays_in_weavehr"),
                pl.col("ricu_start").is_not_null().sum().alias("n_stays_in_ricu"),
                ((pl.col("weavehr_start") - pl.col("ricu_start")) == 0).sum().alias("n_same_start"),
                ((pl.col("weavehr_end") - pl.col("ricu_end")) == 0).sum().alias("n_same_end"),
                ((pl.col("weavehr_end") - pl.col("ricu_end")) < 0).sum().alias("n_weavehr_shorter"),
                ((pl.col("weavehr_end") - pl.col("ricu_end")) > 0).sum().alias("n_weavehr_longer"),
                (pl.col("weavehr_end") - pl.col("ricu_end")).min().alias("min_diff_end"),
                (pl.col("weavehr_end") - pl.col("ricu_end")).max().alias("max_diff_end"),
                (pl.col("weavehr_end") - pl.col("ricu_end")).mean().alias("mean_diff_end"),
                pl.col("ricu_end").is_null().sum().alias("n_excluded_metric_null_ricu_end"),
            ]
        )
    else:
        # Window reports join on stay_id: meaningless across identifier spaces.
        window_differences = window_summary = pl.DataFrame()

    scope_dtypes = {
        "weavehr_dataset_version": pl.String,
        "reference_dataset_version": pl.String,
        "same_version": pl.Boolean,
    }
    scope_columns = [
        pl.lit(value, dtype=scope_dtypes.get(key)).alias(key)
        for key, value in {
            "weavehr_dataset_version": versions.weavehr.version,
            "reference_dataset_version": versions.reference.version,
            "same_version": versions.same_version,
            "versions_verified": versions.versions_verified,
            **scope,
        }.items()
    ]

    if scope["validation_level"] == "not_comparable":
        # No shared stays or concepts: there is nothing to score.
        empty = pl.DataFrame()
        per_stay = coverage = missingness = value_diff = empty
        table = empty
        stay_overlap = key_overlap = empty
        accuracy = pl.select(scope_columns)
    else:
        weavehr_lf = weavehr_metric.lazy()
        reference_lf = reference_metric.lazy()
        per_stay = per_stay_reproduction_report(weavehr_lf, reference_lf, metric_vars)
        accuracy = reproduction_accuracy_summary(per_stay)
        accuracy = accuracy.select([*scope_columns, *[pl.col(c) for c in accuracy.columns]])
        table = pl.concat(
            [table_summary(weavehr_lf, "weavehr"), table_summary(reference_lf, "ricu_reference")]
        )
        stay_overlap = stay_overlap_report(weavehr_lf, reference_lf)
        key_overlap = key_overlap_report(weavehr_lf, reference_lf)
        coverage = coverage_report(weavehr_lf, reference_lf, metric_vars)
        missingness = missingness_report(weavehr_lf, reference_lf, metric_vars)
        value_diff = value_diff_report(weavehr_lf, reference_lf, metric_vars)

    result = RICUComparisonResult(
        weavehr_path=weavehr_path,
        reference_path=reference_path,
        reports_dir=out_dir,
        table_summary=table,
        stay_overlap=stay_overlap,
        key_overlap=key_overlap,
        window_summary=window_summary,
        window_differences=window_differences,
        coverage=coverage,
        missingness=missingness,
        value_diff=value_diff,
        per_stay_reproduction=per_stay,
        reproduction_accuracy=accuracy,
        provenance=provenance,
        scope_overlap=scope_overlap,
        scope_differences=scope_differences,
    )

    if out_dir is not None:
        for name, table_df in result.as_dict().items():
            table_df.write_csv(out_dir / f"{name}.csv")
        if write_normalized_reference:
            reference.write_parquet(out_dir / "ricu_reference_normalized.parquet")
            ricu_windows.write_parquet(out_dir / "ricu_windows_normalized.parquet")

    return result


def default_stay_ids(
    *,
    weavehr_wide_path: str | Path,
    ricu_dynamic_path: str | Path,
    ricu_source: str | None = None,
    stay_crosswalk: str | Path | pl.DataFrame | None = None,
) -> StayIdComparison:
    """Stay identifier spaces from the provenance files and RICU's ID config.

    The WeavEHR space is recorded by :func:`build_and_write_yaib_wide_for_dataset`;
    the RICU source comes from ``ricu_source`` or the RICU export's provenance
    file. Unknown spaces are never assumed to be equal.
    """
    source = ricu_source or read_provenance_field(ricu_dynamic_path, "ricu_source")
    return StayIdComparison(
        weavehr_space=read_provenance_field(weavehr_wide_path, "stay_id_space"),
        reference_space=RICU_STAY_ID_SPACES.get(str(source)) if source else None,
        crosswalk=load_stay_crosswalk(stay_crosswalk) if stay_crosswalk is not None else None,
    )


def resolve_comparison_versions(
    *,
    dataset: str,
    weavehr_wide_path: str | Path,
    ricu_dynamic_path: str | Path,
    dataset_version: str | None = None,
    reference_version: str | None = None,
) -> VersionComparison:
    """Determine the WeavEHR and RICU dataset versions of a comparison.

    The WeavEHR version comes from the wide export's provenance file (written by
    :func:`build_and_write_yaib_wide_for_dataset`), else from an explicit
    ``dataset_version``, else it is unknown. A ``dataset_version`` that
    contradicts the provenance file raises: the export would have to be rebuilt.
    """
    weavehr = read_weavehr_provenance(weavehr_wide_path)
    if weavehr is not None:
        if dataset_version is not None and not versions_equal(weavehr.version, dataset_version):
            raise ValueError(
                f"{weavehr_wide_path} was built from WeavEHR {dataset} version "
                f"{weavehr.version!r}, not dataset_version={dataset_version!r}; rebuild it."
            )
    elif dataset_version is not None:
        weavehr = DatasetVersion(dataset, dataset_version, "explicit")
    else:
        weavehr = DatasetVersion(dataset, None, "unknown")

    reference = resolve_reference_version(
        ricu_source=dataset_ricu_code(dataset),
        reference_data_path=ricu_dynamic_path,
        reference_version=reference_version,
    )
    return VersionComparison(weavehr=weavehr, reference=reference)


def compare_weavehr_wide_to_ricu_for_dataset(
    *,
    dataset: str = "mimic-iv",
    max_hours: int | None = 168,
    output_root: str | Path | None = None,
    concept_root: str | Path | None = None,
    icustays_csv: str | Path | None = None,
    ricu_concept_dict: str | Path | None = None,
    weavehr_wide_path: str | Path | None = None,
    ricu_dynamic_path: str | Path | None = None,
    ricu_stay_windows_path: str | Path | None = None,
    reports_dir: str | Path | None = None,
    dynamic_vars: list[str] | None = None,
    write_normalized_reference: bool = True,
    dataset_version: str | None = None,
    reference_version: str | None = None,
    stay_crosswalk: str | Path | pl.DataFrame | None = None,
) -> RICUComparisonResult:
    """Compare the standard dataset-specific WeavEHR and R/RICU parquet files.

    Versions are resolved with :func:`resolve_comparison_versions` and stay
    identifier spaces with :func:`default_stay_ids`; ``stay_crosswalk``
    (``reference_stay_id``, ``weavehr_stay_id``) maps reference stays onto
    WeavEHR stays where the spaces differ. By default reports go to
    ``reports/<horizon>/weavehr-<v>__ricu-<source>-<v>/``.
    """
    paths = default_dataset_paths(
        dataset=dataset,
        output_root=output_root,
        concept_root=concept_root,
        icustays_csv=icustays_csv,
        ricu_concept_dict=ricu_concept_dict,
    )
    weavehr_path = (
        _as_path(weavehr_wide_path)
        if weavehr_wide_path is not None
        else weavehr_wide_output_path(
            output_root=paths.output_root,
            max_hours=max_hours,
        )
    )
    reference_path = (
        _as_path(ricu_dynamic_path) if ricu_dynamic_path is not None else paths.ricu_dynamic_path
    )
    versions = resolve_comparison_versions(
        dataset=paths.dataset,
        weavehr_wide_path=weavehr_path,
        ricu_dynamic_path=reference_path,
        dataset_version=dataset_version,
        reference_version=reference_version,
    )
    return compare_weavehr_wide_to_ricu(
        weavehr_wide_path=weavehr_path,
        ricu_dynamic_path=reference_path,
        ricu_stay_windows_path=(
            _as_path(ricu_stay_windows_path)
            if ricu_stay_windows_path is not None
            else paths.ricu_stay_windows_path
        ),
        reports_dir=(
            _as_path(reports_dir)
            if reports_dir is not None
            else comparison_reports_dir(
                output_root=paths.output_root,
                max_hours=max_hours,
                scope=scope_label(versions, dataset_ricu_code(paths.dataset)),
            )
        ),
        max_hours=max_hours,
        dynamic_vars=dynamic_vars,
        write_normalized_reference=write_normalized_reference,
        versions=versions,
        stay_ids=default_stay_ids(
            weavehr_wide_path=weavehr_path,
            ricu_dynamic_path=reference_path,
            ricu_source=dataset_ricu_code(paths.dataset),
            stay_crosswalk=stay_crosswalk,
        ),
    )


def display_comparison_overview(result: RICUComparisonResult) -> dict[str, pl.DataFrame]:
    """Return the most useful report tables for compact notebook display.

    Provenance and scope come first: the metrics below only describe the scope
    stated there.
    """
    scope = {
        "provenance": result.provenance,
        "scope_overlap": result.scope_overlap,
        "reproduction_accuracy": result.reproduction_accuracy,
    }
    if result.per_stay_reproduction.is_empty():
        return scope
    return {
        **scope,
        "table_summary": result.table_summary,
        "stay_overlap": result.stay_overlap,
        "key_overlap": result.key_overlap,
        "window_summary": result.window_summary,
        "window_differences_head": result.window_differences.head(20),
        "coverage_by_largest_difference": result.coverage.sort("diff_non_null"),
        "missingness_by_reference_only": result.missingness.sort("only_reference", descending=True),
        "value_diff_by_max_abs_diff": result.value_diff.sort("max_abs_diff", descending=True),
        "non_identical_common_stays_head": result.per_stay_reproduction.filter(
            pl.col("in_both") & ~pl.col("content_identical")
        ).head(20),
    }
