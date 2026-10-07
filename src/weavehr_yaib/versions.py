"""Dataset-version provenance for WeavEHR <-> reference comparisons.

Two datasets with the same name are not assumed to be the same version. Every
comparison records the WeavEHR and the reference dataset version together with
*how* each version was determined, and only a comparison of two verified,
identical versions counts as full validation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import polars as pl

from .io import DATASET_VERSION_COLUMN, filter_dataset_version
from .workspace import step_output_dirs

__all__ = [
    "DATASET_VERSION_COLUMN",
    "DatasetVersion",
    "VersionComparison",
    "classify_relationship",
    "relationship_from_counts",
    "concept_dataset_versions",
    "extracted_dataset_versions",
    "filter_dataset_version",
    "PROVENANCE_ID_KEY",
    "StaleProvenanceError",
    "read_provenance_field",
    "read_weavehr_provenance_data",
    "read_weavehr_provenance",
    "resolve_reference_version",
    "resolve_weavehr_version",
    "scope_label",
    "sink_with_provenance",
    "versions_equal",
    "weavehr_provenance",
    "write_weavehr_provenance",
]

VersionSource = Literal[
    "explicit",
    "provenance_file",
    "concept_column",
    "extraction_dirs",
    "ricu_config",
    "manual_default",
    "unknown",
]

# Sources that state what the data actually is. ``ricu_config`` (the download
# URL in RICU's data-sources.json) and ``manual_default`` are assumptions about
# which version a reference export was built from.
VERIFIED_VERSION_SOURCES: frozenset[str] = frozenset(
    {"explicit", "provenance_file", "concept_column", "extraction_dirs"}
)
ASSUMED_VERSION_SOURCES: frozenset[str] = frozenset({"ricu_config", "manual_default"})

ValidationLevel = Literal[
    "full_same_version",
    "shared_subset_cross_version",
    "shared_subset_unverified_version",
    # Same verified version, but stays are linked through a crosswalk rather
    # than a common identifier space: only the mapped stays are compared.
    "shared_subset_stay_crosswalk",
    "not_comparable",
]

Relationship = Literal[
    "equal",
    "weavehr_superset",
    "reference_superset",
    "partial_overlap",
    "not_directly_comparable",
]

# Versions in the download URLs of RICU's data-sources.json (ricu 0.6.3).
RICU_CONFIG_VERSIONS: dict[str, str] = {
    "eicu": "2.0",
    "eicu_demo": "2.0.1",
    "mimic": "1.4",
    "mimic_demo": "1.4",
    "miiv": "2.2",
    "hirid": "1.1.1",
    "sic": "1.0.6",
}

# RICU's config has no version for these sources.
MANUAL_DEFAULT_REFERENCE_VERSIONS: dict[str, str] = {
    "aumc": "1.0.2",
}

_WEAVEHR_REPRESENTATIONS = {
    "aumc": "OMOP CDM 5.4 (AMSTEL ETL)",
}
_RICU_REPRESENTATION = "native source tables (ricu)"


@dataclass(frozen=True)
class DatasetVersion:
    """One side of a comparison: dataset, version and how the version is known."""

    dataset: str
    version: str | None
    source: VersionSource
    representation: str | None = None

    def __post_init__(self) -> None:
        if (self.version is None) != (self.source == "unknown"):
            raise ValueError(
                "A version source of 'unknown' must go with version=None and vice versa."
            )

    @property
    def verified(self) -> bool:
        """Whether the version describes the data rather than an assumption about it."""
        return self.version is not None and self.source in VERIFIED_VERSION_SOURCES

    @property
    def assumed(self) -> bool:
        return self.source in ASSUMED_VERSION_SOURCES

    def as_dict(self, prefix: str) -> dict[str, str | bool | None]:
        return {
            f"{prefix}_dataset": self.dataset,
            f"{prefix}_dataset_version": self.version,
            f"{prefix}_version_source": self.source,
            f"{prefix}_version_verified": self.verified,
            f"{prefix}_representation": self.representation,
        }


def _version_key(version: str) -> tuple[str, ...]:
    """Normalize ``v2.2.0`` / ``2.2`` to the same comparable key."""
    parts = version.strip().lower().removeprefix("v").split(".")
    parts = [str(int(p)) if p.isdigit() else p for p in parts]
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return tuple(parts)


def versions_equal(a: str | None, b: str | None) -> bool | None:
    """Compare two version strings; ``None`` when either version is unknown."""
    if a is None or b is None:
        return None
    return _version_key(a) == _version_key(b)


def relationship_from_counts(
    n_weavehr: int, n_reference: int, n_shared: int, *, comparable: bool = True
) -> Relationship:
    """Classify two identifier sets from their sizes and intersection size."""
    if not comparable or n_shared == 0:
        return "not_directly_comparable"
    if n_shared == n_weavehr == n_reference:
        return "equal"
    if n_shared == n_reference:
        return "weavehr_superset"
    if n_shared == n_weavehr:
        return "reference_superset"
    return "partial_overlap"


def classify_relationship(
    weavehr: set | frozenset, reference: set | frozenset, *, comparable: bool = True
) -> Relationship:
    """Classify how two identifier sets relate.

    ``comparable=False`` means the identifiers do not share a defensible common
    space, so no set relation is claimed. An empty intersection is likewise not
    directly comparable.
    """
    return relationship_from_counts(
        len(weavehr), len(reference), len(weavehr & reference), comparable=comparable
    )


@dataclass(frozen=True)
class VersionComparison:
    """Version relation between the two sides of a comparison."""

    weavehr: DatasetVersion
    reference: DatasetVersion

    @property
    def same_version(self) -> bool | None:
        return versions_equal(self.weavehr.version, self.reference.version)

    @property
    def versions_verified(self) -> bool:
        return self.weavehr.verified and self.reference.verified

    @property
    def full_scope(self) -> bool:
        """Only verified, identical versions allow the full comparison."""
        return self.same_version is True and self.versions_verified

    def validation_level(self, *, comparable: bool) -> ValidationLevel:
        if not comparable:
            return "not_comparable"
        if self.full_scope:
            return "full_same_version"
        if self.same_version is False and self.versions_verified:
            return "shared_subset_cross_version"
        return "shared_subset_unverified_version"

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            **self.weavehr.as_dict("weavehr"),
            **self.reference.as_dict("reference"),
            "same_version": self.same_version,
            "versions_verified": self.versions_verified,
        }


# ---------------------------------------------------------------------------
# WeavEHR side
# ---------------------------------------------------------------------------


def weavehr_representation(dataset: str) -> str:
    return _WEAVEHR_REPRESENTATIONS.get(dataset.lower(), "native source tables (WeavEHR)")


def extracted_dataset_versions(workspace: str | Path, dataset: str) -> list[str]:
    """Version directories of a dataset's WeavEHR extraction output."""
    versions: set[str] = set()
    for root in step_output_dirs(workspace, dataset):
        if root.is_dir():
            versions.update(p.name for p in root.iterdir() if p.is_dir())
    return sorted(versions)


def concept_dataset_versions(concept_files: list[Path]) -> list[str] | None:
    """Distinct ``dataset_version`` values across concept parquets.

    Returns ``None`` when any file lacks the column: the files then cannot be
    attributed to a version.
    """
    versions: set[str] = set()
    for path in concept_files:
        lf = pl.scan_parquet(path)
        if DATASET_VERSION_COLUMN not in lf.collect_schema().names():
            return None
        values = lf.select(pl.col(DATASET_VERSION_COLUMN).cast(pl.String).unique()).collect()
        versions.update(v for v in values.to_series().to_list() if v is not None)
    return sorted(versions)


_MISSING_VERSION_COLUMN_HINT = (
    "Add the dataset version to the WeavEHR concept outputs via the concept step config:\n"
    "  mapping_configs:\n"
    "    - name: <dataset>\n"
    "      version: <version>\n"
    "      extension_columns:\n"
    '        dataset_version: col("version")'
)


def resolve_weavehr_version(
    *,
    dataset: str,
    concept_files: list[Path],
    workspace: str | Path,
    dataset_version: str | None = None,
) -> DatasetVersion:
    """Determine which WeavEHR dataset version the concept outputs represent.

    Order: explicit ``dataset_version``, the ``dataset_version`` concept column,
    the extraction version directories. Never guesses: several versions without
    an explicit selection, or several extracted versions that the concept
    outputs cannot distinguish, raise ``ValueError``. The returned version is the
    exact string used in the concept column when that column exists, so it can be
    used to filter rows.
    """
    representation = weavehr_representation(dataset)
    in_concepts = concept_dataset_versions(concept_files)
    extracted = extracted_dataset_versions(workspace, dataset)

    if in_concepts:
        if dataset_version is None:
            if len(in_concepts) > 1:
                raise ValueError(
                    f"WeavEHR concept outputs for {dataset!r} contain several dataset versions "
                    f"{in_concepts}; select one with dataset_version=."
                )
            return DatasetVersion(dataset, in_concepts[0], "concept_column", representation)
        for value in in_concepts:
            if versions_equal(value, dataset_version):
                return DatasetVersion(dataset, value, "explicit", representation)
        raise ValueError(
            f"dataset_version={dataset_version!r} is not present in the WeavEHR concept outputs "
            f"for {dataset!r}; available: {in_concepts}."
        )

    if len(extracted) > 1:
        raise ValueError(
            f"Several extracted WeavEHR versions of {dataset!r} exist ({extracted}), but the "
            "concept outputs do not record which version each row comes from, so they cannot "
            f"be separated.\n{_MISSING_VERSION_COLUMN_HINT}"
        )
    if dataset_version is not None:
        if extracted and not versions_equal(extracted[0], dataset_version):
            raise ValueError(
                f"dataset_version={dataset_version!r} does not match the extracted WeavEHR "
                f"version {extracted[0]!r} of {dataset!r}."
            )
        return DatasetVersion(dataset, dataset_version, "explicit", representation)
    if extracted:
        return DatasetVersion(dataset, extracted[0], "extraction_dirs", representation)
    return DatasetVersion(dataset, None, "unknown", representation)


def provenance_path(data_path: str | Path) -> Path:
    """Sidecar file recording the provenance of a parquet export."""
    return Path(data_path).with_suffix(".provenance.json")


# Parquet key-value metadata linking an export to its provenance sidecar.
PROVENANCE_ID_KEY = "weavehr_yaib.provenance_id"


class StaleProvenanceError(ValueError):
    """A provenance sidecar does not belong to the parquet next to it."""


def sink_with_provenance(
    lf: pl.LazyFrame, data_path: str | Path, provenance: dict[str, object] | None
) -> None:
    """Write ``lf`` and, if given, its provenance sidecar with a shared ID.

    Any existing sidecar is removed first, so a writer without provenance never
    leaves a sidecar that describes earlier data.
    """
    data_path = Path(data_path)
    sidecar = provenance_path(data_path)
    sidecar.unlink(missing_ok=True)
    if provenance is None:
        lf.sink_parquet(data_path)
        return
    provenance_id = uuid4().hex
    lf.sink_parquet(data_path, metadata={PROVENANCE_ID_KEY: provenance_id})
    sidecar.write_text(
        json.dumps({**provenance, "provenance_id": provenance_id}, indent=2, default=str)
    )


def weavehr_provenance(version: DatasetVersion, **extra: object) -> dict[str, object]:
    return {**asdict(version), **extra}


def write_weavehr_provenance(
    data_path: str | Path, version: DatasetVersion, **extra: object
) -> Path:
    """Attach provenance to an existing parquet (rewrites it with the shared ID)."""
    data_path = Path(data_path)
    sink_with_provenance(
        pl.read_parquet(data_path).lazy(), data_path, weavehr_provenance(version, **extra)
    )
    return provenance_path(data_path)


def read_weavehr_provenance_data(data_path: str | Path) -> dict | None:
    """The verified provenance of a WeavEHR export, or ``None`` without sidecar.

    Raises :class:`StaleProvenanceError` when the sidecar's ID does not match
    the parquet's metadata: it then describes other (earlier) data.
    """
    sidecar = provenance_path(data_path)
    if not sidecar.is_file():
        return None
    data = json.loads(sidecar.read_text())
    expected = data.get("provenance_id")
    actual = (
        pl.read_parquet_metadata(data_path).get(PROVENANCE_ID_KEY)
        if Path(data_path).is_file()
        else None
    )
    if expected is None or actual != expected:
        raise StaleProvenanceError(
            f"{sidecar} does not belong to {data_path} (stale or mismatched provenance). "
            "Rebuild the export or remove the provenance file."
        )
    return data


def read_provenance_field(data_path: str | Path, key: str, *, verified: bool = True) -> str | None:
    """One value from a ``.provenance.json`` sidecar, or ``None``.

    ``verified=True`` (WeavEHR exports) checks that the sidecar belongs to the
    parquet; reference sidecars written by the R export carry no such ID.
    """
    if verified:
        data = read_weavehr_provenance_data(data_path)
    else:
        sidecar = provenance_path(data_path)
        data = json.loads(sidecar.read_text()) if sidecar.is_file() else None
    value = None if data is None else data.get(key)
    return None if value is None else str(value)


def read_weavehr_provenance(data_path: str | Path) -> DatasetVersion | None:
    data = read_weavehr_provenance_data(data_path)
    if data is None:
        return None
    return DatasetVersion(
        dataset=data["dataset"],
        version=data["version"],
        source=data["source"],
        representation=data.get("representation"),
    )


# ---------------------------------------------------------------------------
# Reference (RICU) side
# ---------------------------------------------------------------------------


def resolve_reference_version(
    *,
    ricu_source: str,
    reference_data_path: str | Path | None = None,
    reference_version: str | None = None,
) -> DatasetVersion:
    """Determine the RICU source dataset version of a reference export.

    Order: explicit ``reference_version``; ``RICU_SOURCE_VERSION`` declared in
    the export's provenance file (verified); the version in RICU's source URL,
    whether recorded in the provenance file or taken from the RICU config
    (assumed: local data may differ from what RICU would download); the manual
    default (assumed); otherwise unknown.
    """
    dataset = f"ricu:{ricu_source}"
    if reference_version is not None:
        return DatasetVersion(dataset, reference_version, "explicit", _RICU_REPRESENTATION)

    if reference_data_path is not None:
        path = provenance_path(reference_data_path)
        if path.is_file():
            data = json.loads(path.read_text())
            declared = data.get("source_version_declared")
            if declared:
                return DatasetVersion(
                    dataset, str(declared), "provenance_file", _RICU_REPRESENTATION
                )
            from_url = data.get("source_version_from_url")
            if from_url:
                return DatasetVersion(dataset, str(from_url), "ricu_config", _RICU_REPRESENTATION)

    if ricu_source in RICU_CONFIG_VERSIONS:
        return DatasetVersion(
            dataset, RICU_CONFIG_VERSIONS[ricu_source], "ricu_config", _RICU_REPRESENTATION
        )
    if ricu_source in MANUAL_DEFAULT_REFERENCE_VERSIONS:
        return DatasetVersion(
            dataset,
            MANUAL_DEFAULT_REFERENCE_VERSIONS[ricu_source],
            "manual_default",
            _RICU_REPRESENTATION,
        )
    return DatasetVersion(dataset, None, "unknown", _RICU_REPRESENTATION)


def scope_label(versions: VersionComparison, ricu_source: str) -> str:
    """Directory-safe label naming both versions, e.g. ``weavehr-3.1__ricu-miiv-2.2``."""
    w = versions.weavehr.version or "unknown"
    r = versions.reference.version or "unknown"
    return f"weavehr-{w}__ricu-{ricu_source}-{r}"
