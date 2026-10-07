"""YAIB-wide export across every WeavEHR concept parquet present for a dataset."""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from pathlib import Path

import polars as pl

from .aggregation import uses_ricu_aggregation
from .concepts import RICU_TO_WEAVEHR
from .io import (
    require_concept_column,
    scan_dataset_stays,
    scan_weavehr_subject_concept_hours,
    stay_link_column,
)
from .ricu_meta import RicuConceptMeta
from .stays import (
    SIC_CASE_ID_HINT,
    SIC_DATASETS,
    dataset_stay_spec,
    find_dataset_stay_file,
    require_raw_stay_table_compatible,
    require_weavehr_stays,
)
from .versions import DatasetVersion, resolve_weavehr_version, write_weavehr_provenance
from .workspace import (
    concept_root_from_output,
    resolve_weavehr_workspace,
    weavehr_aumc_stays,
    weavehr_sic_stays,
    yaib_root_from_output,
)

__all__ = [
    "AllConceptsExportResult",
    "ConceptFile",
    "build_all_concepts_wide",
    "concept_root_from_output",
    "discover_dataset_concepts",
    "resolve_weavehr_workspace",
    "write_all_concepts_wide",
    "yaib_root_from_output",
]


@dataclass(frozen=True)
class ConceptFile:
    name: str
    version: str | None
    path: Path


@dataclass(frozen=True)
class AllConceptsExportResult:
    output_path: Path
    manifest_path: Path
    concepts: tuple[str, ...]
    n_rows: int
    n_stays: int
    dataset_version: DatasetVersion | None = None


def discover_dataset_concepts(concept_root: str | Path, dataset: str) -> list[ConceptFile]:
    """Discover all concept parquets named ``<dataset>.parquet``.

    WeavEHR's standard layout is ``concept/<concept>/<version>/<dataset>.parquet``.
    Nested concept identifiers are supported as well; the concept name is the
    path between ``concept_root`` and the version directory.
    """
    root = Path(concept_root).expanduser().resolve()
    candidates = sorted(root.rglob(f"{dataset}.parquet"))
    if not candidates:
        candidates = sorted(root.rglob(f"{dataset.replace('-', '_')}.parquet"))

    found: list[ConceptFile] = []
    for path in candidates:
        rel = path.relative_to(root)
        if len(rel.parts) < 2:
            continue
        version = rel.parts[-2] if len(rel.parts) >= 3 else None
        concept_parts = rel.parts[:-2] if len(rel.parts) >= 3 else rel.parts[:-1]
        name = "/".join(concept_parts) or path.parent.name
        # Most WeavEHR concept roots are <concept>/<version>/<dataset>.parquet.
        if len(rel.parts) == 3:
            name = rel.parts[0]
        found.append(ConceptFile(name=name, version=version, path=path))

    # Keep one deterministic file per logical concept if recursive aliases collide.
    by_name: dict[str, ConceptFile] = {}
    for item in found:
        by_name[item.name] = item
    return [by_name[name] for name in sorted(by_name)]


def _grid_from_normalized_stays(stays: pl.LazyFrame, max_hours: int | None) -> pl.LazyFrame:
    los = stays.with_columns((pl.col("outtime_hours") - pl.col("intime_hours")).alias("los_hours"))
    end_expr = pl.col("los_hours").floor().cast(pl.Int64)
    if max_hours is not None:
        end_expr = pl.min_horizontal(end_expr, pl.lit(max_hours))
    return (
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


# Additional RICU concepts that are not part of the standard dynamic-variable
# mapping but do have relevant hourly aggregation metadata.
_RICU_AGGREGATION_TO_WEAVEHR = {
    **RICU_TO_WEAVEHR,
    "dobu_dur": "dobutamine_duration",
    "dopa_dur": "dopamine_duration",
    "epi_dur": "epinephrine_duration",
    "norepi_dur": "norepinephrine_duration",
}

_WEAVEHR_TO_RICU_AGGREGATION = {
    weavehr_name: ricu_name for ricu_name, weavehr_name in _RICU_AGGREGATION_TO_WEAVEHR.items()
}


def _aggregate_expr(column: str, aggregate: str) -> pl.Expr:
    """Aggregate one hourly concept using the requested aggregation function."""
    aggregate = aggregate.lower()

    if aggregate == "mean":
        return pl.col(column).mean()
    if aggregate == "median":
        return pl.col(column).median()
    if aggregate == "sum":
        return pl.col(column).sum()
    if aggregate == "min":
        return pl.col(column).min()
    if aggregate == "max":
        return pl.col(column).max()
    if aggregate == "first":
        return pl.col(column).first()
    if aggregate == "last":
        return pl.col(column).last()

    raise ValueError(f"Unsupported aggregation: {aggregate!r}")


def _concept_table(
    item: ConceptFile,
    *,
    stays: pl.LazyFrame | None,
    subject_is_stay: bool,
    numeric_time_scale_hours: float,
    max_hours: int | None,
    ricu_meta: RicuConceptMeta | None,
    dataset_version: str | None = None,
) -> pl.LazyFrame:
    events = scan_weavehr_subject_concept_hours(
        item.path,
        numeric_scale_hours=numeric_time_scale_hours,
        dataset_version=dataset_version,
    )
    if stays is None:
        if not subject_is_stay:
            raise ValueError(
                f"No ICU-stay table available for {item.name!r}; set the dataset stay path."
            )
        mapped = events.with_columns(
            pl.col("subject_id").alias("stay_id"),
            pl.col("time_hours").floor().cast(pl.Int64).alias("time"),
        )
    else:
        link = stay_link_column(events.collect_schema().names())
        if link is not None:
            mapped = events.with_columns(pl.col(link).cast(pl.Int64).alias("stay_id")).join(
                stays, on=["subject_id", "stay_id"], how="inner"
            )
        else:
            mapped = events.join(stays, on="subject_id", how="inner")

        mapped = (
            mapped.filter(
                (pl.col("time_hours") >= pl.col("intime_hours"))
                & (
                    pl.col("outtime_hours").is_null()
                    | (pl.col("time_hours") <= pl.col("outtime_hours"))
                )
            )
            .with_columns(
                (pl.col("time_hours") - pl.col("intime_hours")).floor().cast(pl.Int64).alias("time")
            )
        )
    mapped = mapped.filter(pl.col("time") >= 0)
    if max_hours is not None:
        mapped = mapped.filter(pl.col("time") <= max_hours)
    ricu_name = _WEAVEHR_TO_RICU_AGGREGATION.get(item.name)
    aggregate = (
        ricu_meta.aggregate_for(ricu_name, default="median")
        if ricu_meta is not None and ricu_name is not None
        else "mean"
    )

    return (
        mapped.group_by("stay_id", "time")
        .agg(_aggregate_expr("numeric_value", aggregate).alias(item.name))
        .select("stay_id", "time", item.name)
    )


def build_all_concepts_wide(
    *,
    dataset: str,
    concept_root: str | Path,
    stays_path: str | Path | None = None,
    max_hours: int | None = None,
    include_grid: bool = True,
    ricu_concept_dict: str | Path | None = None,
    normalized_stays: pl.LazyFrame | None = None,
    dataset_version: str | None = None,
) -> tuple[pl.LazyFrame, list[ConceptFile]]:
    """Build a numeric YAIB-wide table from every available WeavEHR concept.

    Every discovered concept is represented as a column. WeavEHR concepts whose
    ``numeric_value`` is entirely null therefore remain an all-null column; this
    deliberately keeps the full concept inventory visible instead of silently
    dropping text/static concepts from the schema.
    """
    concepts = discover_dataset_concepts(concept_root, dataset)
    if not concepts:
        raise FileNotFoundError(
            f"No concept parquets for dataset {dataset!r} below {Path(concept_root)}"
        )

    spec = dataset_stay_spec(dataset)
    ricu_meta = (
        RicuConceptMeta.from_json(ricu_concept_dict)
        if ricu_concept_dict is not None and uses_ricu_aggregation(dataset)
        else None
    )
    if normalized_stays is not None:
        stays = normalized_stays
    else:
        resolved_stays = (
            Path(stays_path).expanduser().resolve()
            if stays_path
            else find_dataset_stay_file(dataset)
        )
        if resolved_stays is not None:
            require_raw_stay_table_compatible(spec.dataset)
        stays = scan_dataset_stays(resolved_stays, spec) if resolved_stays is not None else None
    if stays is None:
        require_weavehr_stays(dataset)

    tables = [
        _concept_table(
            item,
            stays=stays,
            subject_is_stay=spec.subject_is_stay,
            numeric_time_scale_hours=spec.numeric_time_scale_hours,
            max_hours=max_hours,
            ricu_meta=ricu_meta,
            dataset_version=dataset_version,
        )
        for item in concepts
    ]
    wide = reduce(
        lambda left, right: left.join(right, on=["stay_id", "time"], how="full", coalesce=True),
        tables,
    )

    can_grid = stays is not None and (spec.outtime_col is not None or max_hours is not None)
    if include_grid and can_grid:
        assert stays is not None
        wide = _grid_from_normalized_stays(stays, max_hours).join(
            wide, on=["stay_id", "time"], how="left"
        )
    elif max_hours is not None:
        wide = wide.filter(pl.col("time") <= max_hours)

    columns = ["stay_id", "time", *[item.name for item in concepts]]
    return wide.select(columns).sort("stay_id", "time"), concepts


def write_all_concepts_wide(
    *,
    dataset: str,
    weavehr_output: str | Path,
    concept_root: str | Path | None = None,
    stays_path: str | Path | None = None,
    max_hours: int | None = None,
    include_grid: bool = True,
    output_name: str | None = None,
    output_root: str | Path | None = None,
    ricu_concept_dict: str | Path | None = None,
    dataset_version: str | None = None,
) -> AllConceptsExportResult:
    """Write the full-concept wide parquet.

    By default, output is written under ``<workspace>/yaib/<dataset>``.
    If ``output_root`` is provided, that directory is used instead.

    The WeavEHR dataset version is resolved (see
    :func:`~weavehr_yaib.versions.resolve_weavehr_version`) and recorded in the
    manifest and a ``.provenance.json`` sidecar. Several versions require an
    explicit ``dataset_version``.
    """
    workspace = resolve_weavehr_workspace(weavehr_output)
    croot = (
        Path(concept_root).expanduser().resolve()
        if concept_root
        else concept_root_from_output(weavehr_output)
    )

    if output_root is None:
        dataset_dir = workspace / "yaib" / dataset
    else:
        dataset_dir = Path(output_root).expanduser().resolve()
    dataset_dir.mkdir(parents=True, exist_ok=True)
    name = output_name or (
        "weavehr_all_concepts_wide.parquet"
        if max_hours is None
        else f"weavehr_all_concepts_wide_{max_hours}h.parquet"
    )
    out = dataset_dir / name
    manifest = dataset_dir / (out.stem + "_concepts.csv")

    version = resolve_weavehr_version(
        dataset=dataset,
        concept_files=[x.path for x in discover_dataset_concepts(croot, dataset)],
        workspace=croot.parent,
        dataset_version=dataset_version,
    )

    normalized_stays = None
    if dataset.lower() == "aumc" and stays_path is None:
        normalized_stays = weavehr_aumc_stays(workspace, version=version.version)
    if dataset.lower() in SIC_DATASETS and stays_path is None:
        require_concept_column(
            [x.path for x in discover_dataset_concepts(croot, dataset)], "case_id", SIC_CASE_ID_HINT
        )
        normalized_stays = weavehr_sic_stays(workspace, version=version.version)

    wide, concepts = build_all_concepts_wide(
        dataset=dataset,
        concept_root=croot,
        stays_path=stays_path,
        normalized_stays=normalized_stays,
        max_hours=max_hours,
        include_grid=include_grid,
        ricu_concept_dict=ricu_concept_dict,
        dataset_version=version.version,
    )
    wide.sink_parquet(out)
    write_weavehr_provenance(out, version, max_hours=max_hours)
    pl.DataFrame(
        {
            "concept": [x.name for x in concepts],
            "concept_version": [x.version for x in concepts],
            "dataset_version": [version.version] * len(concepts),
            "dataset_version_source": [version.source] * len(concepts),
            "source_parquet": [str(x.path) for x in concepts],
        },
        schema_overrides={"dataset_version": pl.String},
    ).write_csv(manifest)
    summary = (
        pl.scan_parquet(out)
        .select(pl.len().alias("n_rows"), pl.col("stay_id").n_unique().alias("n_stays"))
        .collect()
        .row(0)
    )
    return AllConceptsExportResult(
        output_path=out,
        manifest_path=manifest,
        concepts=tuple(x.name for x in concepts),
        n_rows=int(summary[0]),
        n_stays=int(summary[1]),
        dataset_version=version,
    )
