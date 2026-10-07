"""High-level pipelines for WeavEHR -> YAIB mortality dynamic output."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .config import WeavEHRYAIBConfig, load_config
from .transform import build_dynamic_table, resolve_build_dataset_version, write_dynamic_table


def build_mortality_dynamic_wide(config: WeavEHRYAIBConfig) -> pl.LazyFrame:
    """Build the YAIB mortality dynamic wide table from a resolved config.

    The mortality use case is defined by ``config.dynamic_vars``. The resulting
    table contains ``stay_id``, integer ``time`` in YAIB hours, and one column
    per configured dynamic variable that could be loaded.
    """
    # Unit conversion is intentionally not applied here yet because the imported
    # converter consumed WeavEHR numeric_value directly. The loaded unit_mapping
    # is kept in the config as an explicit extension point for follow-up work.
    dataset_version = resolve_build_dataset_version(
        concept_root=config.concept_root,
        dataset=config.dataset,
        version=config.version,
        dynamic_vars=config.dynamic_vars,
        concept_mapping=config.concept_mapping,
        dataset_version=config.dataset_version,
    ).version
    return build_dynamic_table(
        concept_root=config.concept_root,
        icustays_csv=config.icustays_csv,
        ricu_concept_dict=config.ricu_concept_dict,
        dataset=config.dataset,
        version=config.version,
        dynamic_vars=config.dynamic_vars,
        concept_mapping=config.concept_mapping,
        aggregation_mode=config.aggregation_mode,  # type: ignore[arg-type]
        include_grid=config.include_grid,
        max_hours=config.max_hours,
        grid_end_rounding=config.grid_end_rounding,  # type: ignore[arg-type]
        filter_to_icu_window=config.filter_to_icu_window,
        missing_concepts=config.missing_concepts,  # type: ignore[arg-type]
        dataset_version=dataset_version,
    )


def build_mortality_dynamic_wide_from_config(config_path: str | Path) -> pl.LazyFrame:
    """Load config and build the YAIB mortality dynamic wide lazy frame."""
    return build_mortality_dynamic_wide(load_config(config_path))


def write_mortality_dynamic_wide_from_config(
    config_path: str | Path,
    output_path: str | Path | None = None,
    dataset_version: str | None = None,
) -> Path:
    """Load config, build the table and write it with provenance to parquet.

    ``dataset_version`` overrides ``concepts.dataset_version`` of the config.
    """
    config = load_config(config_path)
    out = Path(output_path) if output_path is not None else config.output_path
    if out is None:
        raise ValueError("No output path provided. Set output.path in config or pass output_path.")
    write_dynamic_table(
        output_path=out,
        concept_root=config.concept_root,
        icustays_csv=config.icustays_csv,
        ricu_concept_dict=config.ricu_concept_dict,
        dataset=config.dataset,
        version=config.version,
        dynamic_vars=config.dynamic_vars,
        concept_mapping=config.concept_mapping,
        aggregation_mode=config.aggregation_mode,  # type: ignore[arg-type]
        include_grid=config.include_grid,
        max_hours=config.max_hours,
        grid_end_rounding=config.grid_end_rounding,  # type: ignore[arg-type]
        filter_to_icu_window=config.filter_to_icu_window,
        missing_concepts=config.missing_concepts,  # type: ignore[arg-type]
        dataset_version=dataset_version or config.dataset_version,
    )
    return out


def run_from_config(config_path: str | Path) -> Path:
    """Alias for the config-first write path."""
    return write_mortality_dynamic_wide_from_config(config_path)
