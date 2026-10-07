"""Config-first API for WeavEHR -> YAIB mortality dynamic conversion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WeavEHRYAIBConfig:
    """Resolved configuration for building a YAIB mortality dynamic table."""

    concept_root: Path
    dataset: str = "mimic-iv"
    version: str | None = "1.0.0"
    # WeavEHR dataset version (``version`` is the concept version). None
    # resolves it from the project and fails if several versions are present.
    dataset_version: str | None = None
    icustays_csv: Path | None = None
    ricu_concept_dict: Path | None = None
    dynamic_vars: list[str] | None = None
    concept_mapping: dict[str, str] | None = None
    unit_mapping: dict[str, Any] | None = None
    aggregation_mode: str = "ricu"
    include_grid: bool = False
    max_hours: int | None = 168
    grid_end_rounding: str = "floor"
    filter_to_icu_window: bool = True
    missing_concepts: str = "warn"
    output_path: Path | None = None


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return data


def _resolve_path(value: str | Path | None, *, base_dir: Path) -> Path | None:
    if value in (None, "", "null"):
        return None
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path).resolve()


def _load_dynamic_vars(path: Path | None) -> list[str] | None:
    if path is None:
        return None
    data = _read_yaml(path)
    values = data.get("dynamic_vars") or data.get("mortality_dynamic_vars")
    if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
        raise ValueError(
            f"Dynamic vars YAML must contain a string list under 'dynamic_vars': {path}"
        )
    return values


def _load_concept_mapping(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    data = _read_yaml(path)
    mapping = data.get("concept_mapping", data)
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        raise ValueError(f"Concept mapping YAML must contain string-to-string mapping: {path}")
    return dict(mapping)


def _load_unit_mapping(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data = _read_yaml(path)
    mapping = data.get("unit_mapping", data)
    if not isinstance(mapping, dict):
        raise ValueError(f"Unit mapping YAML must contain a mapping: {path}")
    return mapping


def load_config(path: str | Path) -> WeavEHRYAIBConfig:
    """Load and resolve a ``weavehr_yaib.yml`` config file."""
    config_path = Path(path).resolve()
    base_dir = config_path.parent
    data = _read_yaml(config_path)

    concepts = data.get("concepts", {}) or {}
    if not isinstance(concepts, dict):
        raise ValueError("'concepts' must be a mapping.")
    concept_root = _resolve_path(concepts.get("path"), base_dir=base_dir)
    if concept_root is None:
        raise ValueError("Config requires concepts.path.")

    yaib = data.get("yaib", {}) or {}
    if not isinstance(yaib, dict):
        raise ValueError("'yaib' must be a mapping.")

    dynamic_vars_path = _resolve_path(yaib.get("dynamic_vars"), base_dir=base_dir)
    concept_mapping_path = _resolve_path(yaib.get("concept_mapping"), base_dir=base_dir)
    unit_mapping_path = _resolve_path(yaib.get("unit_mapping"), base_dir=base_dir)

    aggregation = data.get("aggregation", {}) or {}
    grid = data.get("grid", {}) or {}
    time = data.get("time", {}) or {}
    output = data.get("output", {}) or {}

    max_hours = grid.get("max_hours", 168)
    if max_hours == -1:
        max_hours = None

    return WeavEHRYAIBConfig(
        concept_root=concept_root,
        dataset=str(concepts.get("dataset", "mimic-iv")),
        version=concepts.get("version", "1.0.0"),
        dataset_version=(
            None
            if concepts.get("dataset_version") in (None, "", "null")
            else str(concepts.get("dataset_version"))
        ),
        icustays_csv=_resolve_path(data.get("icustays_csv"), base_dir=base_dir),
        ricu_concept_dict=_resolve_path(data.get("ricu_concept_dict"), base_dir=base_dir),
        dynamic_vars=_load_dynamic_vars(dynamic_vars_path),
        concept_mapping=_load_concept_mapping(concept_mapping_path),
        unit_mapping=_load_unit_mapping(unit_mapping_path),
        aggregation_mode=str(aggregation.get("mode", "ricu")),
        include_grid=bool(grid.get("include", False)),
        max_hours=max_hours,
        grid_end_rounding=str(grid.get("end_rounding", "floor")),
        filter_to_icu_window=bool(time.get("filter_to_icu_window", True)),
        missing_concepts=str(data.get("missing_concepts", "warn")),
        output_path=_resolve_path(output.get("path"), base_dir=base_dir),
    )
