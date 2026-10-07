"""Dataset-version resolution, classification and version-aware wide export."""

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from weavehr_yaib import build_and_write_yaib_wide_for_dataset
from weavehr_yaib.versions import (
    DatasetVersion,
    VersionComparison,
    classify_relationship,
    read_provenance_field,
    read_weavehr_provenance,
    resolve_reference_version,
    resolve_weavehr_version,
    versions_equal,
)


@pytest.mark.parametrize(
    ("weavehr", "reference", "expected"),
    [
        ({1, 2}, {1, 2}, "equal"),
        ({1, 2, 3}, {1, 2}, "weavehr_superset"),
        ({1}, {1, 2}, "reference_superset"),
        ({1, 2}, {2, 3}, "partial_overlap"),
        ({1}, {2}, "not_directly_comparable"),
        (set(), set(), "not_directly_comparable"),
    ],
)
def test_classify_relationship(weavehr: set, reference: set, expected: str) -> None:
    assert classify_relationship(weavehr, reference) == expected


def test_classify_relationship_without_common_identifier_space() -> None:
    assert classify_relationship({1}, {1}, comparable=False) == "not_directly_comparable"


def test_versions_equal_normalizes_and_keeps_unknown() -> None:
    assert versions_equal("2.2", "v2.2.0") is True
    assert versions_equal("3.1", "2.2") is False
    assert versions_equal(None, "2.2") is None


def _v(version: str | None, source: str) -> DatasetVersion:
    return DatasetVersion("x", version, source)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("weavehr", "reference", "same", "level"),
    [
        (_v("2.2", "extraction_dirs"), _v("2.2", "provenance_file"), True, "full_same_version"),
        (_v("3.1", "explicit"), _v("2.2", "provenance_file"), False, "shared_subset_cross_version"),
        # Assumed reference versions never yield full validation.
        (_v("2.2", "explicit"), _v("2.2", "ricu_config"), True, "shared_subset_unverified_version"),
        (
            _v("1.5.0", "explicit"),
            _v("1.0.2", "manual_default"),
            False,
            "shared_subset_unverified_version",
        ),
        (
            _v(None, "unknown"),
            _v("2.2", "provenance_file"),
            None,
            "shared_subset_unverified_version",
        ),
    ],
)
def test_validation_levels(weavehr, reference, same, level) -> None:
    versions = VersionComparison(weavehr=weavehr, reference=reference)
    assert versions.same_version is same
    assert versions.validation_level(comparable=True) == level
    assert versions.validation_level(comparable=False) == "not_comparable"


def test_assumed_versions_are_not_verified() -> None:
    assert not _v("2.2", "ricu_config").verified
    assert not _v("1.0.2", "manual_default").verified
    assert _v("2.2", "explicit").verified
    with pytest.raises(ValueError):
        DatasetVersion("x", None, "explicit")


def test_reference_version_sources(tmp_path: Path) -> None:
    data = tmp_path / "ricu_dynamic_vars_miiv.parquet"

    default = resolve_reference_version(ricu_source="miiv", reference_data_path=data)
    assert (default.version, default.source, default.verified) == ("2.2", "ricu_config", False)

    aumc = resolve_reference_version(ricu_source="aumc")
    assert (aumc.version, aumc.source, aumc.verified) == ("1.0.2", "manual_default", False)

    assert resolve_reference_version(ricu_source="other").source == "unknown"

    sidecar = tmp_path / "ricu_dynamic_vars_miiv.provenance.json"
    sidecar.write_text(
        json.dumps({"source_version_from_url": "2.2", "source_version_declared": None})
    )
    from_url = resolve_reference_version(ricu_source="miiv", reference_data_path=data)
    assert (from_url.source, from_url.verified) == ("ricu_config", False)

    sidecar.write_text(
        json.dumps({"source_version_from_url": "2.2", "source_version_declared": "3.1"})
    )
    declared = resolve_reference_version(ricu_source="miiv", reference_data_path=data)
    assert (declared.version, declared.source, declared.verified) == (
        "3.1",
        "provenance_file",
        True,
    )

    explicit = resolve_reference_version(
        ricu_source="miiv", reference_data_path=data, reference_version="2.2"
    )
    assert explicit.source == "explicit"


# ---------------------------------------------------------------------------
# WeavEHR version resolution on a synthetic project
# ---------------------------------------------------------------------------


def _concept(path: Path, versions: list[str] | None) -> Path:
    n = len(versions) if versions else 1
    df = pl.DataFrame(
        {
            "subject_id": [1] * n,
            "time": pl.Series([datetime(2020, 1, 1, 1, 30)] * n, dtype=pl.Datetime("us")),
            "numeric_value": pl.Series([80.0 + i for i in range(n)], dtype=pl.Float32),
            "visit_occurrence_id": ["10"] * n,
        }
    )
    if versions:
        df = df.with_columns(pl.Series("dataset_version", versions))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    return path


def _extract_aumc(project: Path, version: str) -> None:
    base = project / "workspace/extraction/aumc" / version / "visit_occurrence"
    base.mkdir(parents=True)
    for name, hour in (("VISIT_START", 0), ("VISIT_END", 5)):
        pl.DataFrame(
            {
                "subject_id": [1],
                "time": pl.Series([datetime(2020, 1, 1, hour)], dtype=pl.Datetime("us")),
                "visit_occurrence_id": [10],
            }
        ).write_parquet(base / f"{name}.parquet")


def _project(tmp_path: Path, extracted: list[str], concept_versions: list[str] | None) -> Path:
    project = tmp_path / "project"
    for sub in ("datasets", "configs"):
        (project / sub).mkdir(parents=True)
    for version in extracted:
        _extract_aumc(project, version)
    _concept(project / "workspace/concept/heart_rate/1.0.0/aumc.parquet", concept_versions)
    return project


def _resolve(project: Path, dataset_version: str | None = None) -> DatasetVersion:
    return resolve_weavehr_version(
        dataset="aumc",
        concept_files=[project / "workspace/concept/heart_rate/1.0.0/aumc.parquet"],
        workspace=project / "workspace",
        dataset_version=dataset_version,
    )


def test_weavehr_version_from_extraction_dirs(tmp_path: Path) -> None:
    version = _resolve(_project(tmp_path, ["1.5.0"], None))
    assert (version.version, version.source, version.verified) == ("1.5.0", "extraction_dirs", True)
    assert version.representation == "OMOP CDM 5.4 (AMSTEL ETL)"


def test_weavehr_version_unknown_without_any_evidence(tmp_path: Path) -> None:
    version = _resolve(_project(tmp_path, [], None))
    assert (version.version, version.source) == (None, "unknown")


def test_several_extracted_versions_without_version_column_fail(tmp_path: Path) -> None:
    project = _project(tmp_path, ["1.5.0", "1.6.0"], None)
    for explicit in (None, "1.5.0"):
        with pytest.raises(ValueError, match="dataset_version: col"):
            _resolve(project, explicit)


def test_explicit_version_must_match_extraction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not match"):
        _resolve(_project(tmp_path, ["1.5.0"], None), "1.6.0")


def test_version_column_requires_selection_when_ambiguous(tmp_path: Path) -> None:
    project = _project(tmp_path, ["1.5.0", "1.6.0"], ["1.5.0", "1.6.0"])
    with pytest.raises(ValueError, match="several dataset versions"):
        _resolve(project)
    with pytest.raises(ValueError, match="not present"):
        _resolve(project, "2.0")
    assert _resolve(project, "1.6.0").source == "explicit"


def test_wide_export_selects_one_version_and_writes_provenance(tmp_path: Path) -> None:
    project = _project(tmp_path, ["1.5.0", "1.6.0"], ["1.5.0", "1.6.0"])
    concept_dict = tmp_path / "concept-dict.json"
    concept_dict.write_text("{}")

    def export(dataset_version: str | None):
        return build_and_write_yaib_wide_for_dataset(
            dataset="aumc",
            max_hours=168,
            output_root=tmp_path / "out",
            concept_root=project / "workspace/concept",
            ricu_concept_dict=concept_dict,
            dynamic_vars=["hr"],
            dataset_version=dataset_version,
        )

    with pytest.raises(ValueError, match="several dataset versions"):
        export(None)

    result = export("1.6.0")
    wide = pl.read_parquet(result.output_path).filter(pl.col("hr").is_not_null())
    # Only the 1.6.0 row (value 81) is used, not the mean over both versions.
    assert wide.select("stay_id", "time", "hr").rows() == [(10, 1, 81.0)]
    assert result.dataset_version == read_weavehr_provenance(result.output_path)
    assert result.dataset_version.version == "1.6.0"
    # Stays come from WeavEHR visit events: OMOP visit_occurrence_id space.
    assert read_provenance_field(result.output_path, "stay_source") == "weavehr_visit_events"
    assert (
        read_provenance_field(result.output_path, "stay_id_space")
        == "omop:visit_occurrence.visit_occurrence_id"
    )
