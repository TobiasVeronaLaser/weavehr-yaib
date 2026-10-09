"""Dataset x concept RICU validation status (R / R+ / R!).

A compact evidence table, one row per dataset and RICU concept, assembled from
results that already exist; nothing is re-compared here:

* the item review summary (:func:`~weavehr_yaib.item_review.build_item_review`)
  says whether RICU defines the concept for the source and whether WeavEHR
  produced it;
* the comparison provenance (:func:`~weavehr_yaib.workflow.compare_weavehr_wide_to_ricu`)
  gives the dataset-level ``validation_level`` and ``comparison_scope``;
* the comparison ``coverage`` table says which concepts were actually compared.

Statuses:

* ``R``  -- RICU defines the concept for this source.
* ``R+`` -- ``R``, the concept has values on both sides in ``coverage`` and the
  comparison is a same-version one (:data:`R_PLUS_VALIDATION_LEVELS`). Never
  from cross-version, unverified-version or not comparable comparisons.
* ``R!`` -- ``R``, but direct comparison of this concept is explicitly declared
  not meaningful (``not_comparable_concepts``). It is never derived from a
  missing comparison or from a dataset-level ``not_comparable`` result.
* no status (null) -- RICU does not define the concept for this source.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import polars as pl

from .item_review import ItemReview
from .versions import versions_equal
from .workflow import RICUComparisonResult

RICUStatus = Literal["R", "R+", "R!"]

# Same verified version: all concepts (full) or the crosswalk-mapped stays.
R_PLUS_VALIDATION_LEVELS: frozenset[str] = frozenset(
    {"full_same_version", "shared_subset_stay_crosswalk"}
)

OUTPUT_COLUMNS = (
    "dataset",
    "ricu_concept",
    "weavehr_concept",
    "reference_concept_defined",
    "weavehr_concept_found",
    "validation_level",
    "comparison_scope",
    "coverage_compared",
    "ricu_status",
    "reason",
    "weavehr_dataset_version",
    "reference_dataset_version",
)
OUTPUT_SCHEMA = {
    "dataset": pl.String,
    "ricu_concept": pl.String,
    "weavehr_concept": pl.String,
    "reference_concept_defined": pl.Boolean,
    "weavehr_concept_found": pl.Boolean,
    "validation_level": pl.String,
    "comparison_scope": pl.String,
    "coverage_compared": pl.Boolean,
    "ricu_status": pl.String,
    "reason": pl.String,
    "weavehr_dataset_version": pl.String,
    "reference_dataset_version": pl.String,
}
OUTPUT_NAME = "dataset_concept_validation"


@dataclass(frozen=True)
class ComparisonEvidence:
    """The parts of a RICU comparison the validation status depends on."""

    provenance: pl.DataFrame
    coverage: pl.DataFrame

    @classmethod
    def from_result(cls, result: RICUComparisonResult) -> ComparisonEvidence:
        return cls(provenance=result.provenance, coverage=result.coverage)


def _read_report_csv(path: Path) -> pl.DataFrame:
    # Strings only: versions such as "2.2" must not become floats. Reports with
    # nothing to score (not_comparable) are written as empty files.
    if path.stat().st_size == 0 or not path.read_text().strip():
        return pl.DataFrame()
    return pl.read_csv(path, infer_schema=False)


def read_comparison_evidence(reports_dir: str | Path) -> ComparisonEvidence:
    """Read ``provenance.csv`` and ``coverage.csv`` from one comparison reports dir.

    ``reports_dir`` is the directory written by
    :func:`~weavehr_yaib.workflow.compare_weavehr_wide_to_ricu`, e.g.
    ``comparison_reports_dir(output_root=..., max_hours=..., scope=...)``.
    """
    out = Path(reports_dir)
    provenance_file = out / "provenance.csv"
    if not provenance_file.is_file():
        raise FileNotFoundError(f"No comparison provenance at {provenance_file}.")
    coverage_file = out / "coverage.csv"
    coverage = _read_report_csv(coverage_file) if coverage_file.is_file() else pl.DataFrame()
    return ComparisonEvidence(provenance=_read_report_csv(provenance_file), coverage=coverage)


def _as_bool(value: object) -> bool | None:
    """Booleans from in-memory tables or from CSVs read as strings."""
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    if text == "":
        return None
    raise ValueError(f"Not a boolean: {value!r}")


def _as_str(value: object) -> str | None:
    return None if value is None or value == "" else str(value)


def _single(values: Iterable[object], column: str) -> object:
    distinct = set(values)
    if len(distinct) > 1:
        raise ValueError(f"Item review summary mixes several {column} values: {sorted(distinct)}")
    return next(iter(distinct), None)


def _compared_concepts(coverage: pl.DataFrame) -> dict[str, bool]:
    """Concepts in ``coverage`` -> whether both sides have non-null values."""
    if coverage.is_empty():
        return {}
    rows = coverage.select(
        pl.col("concept").cast(pl.String),
        pl.col("weavehr_non_null").cast(pl.Int64),
        pl.col("reference_non_null").cast(pl.Int64),
    ).iter_rows()
    return {c: bool(w) and bool(r) for c, w, r in rows}


def _check_consistent(label: str, review_value: str | None, comparison_value: str | None) -> None:
    if review_value is None or comparison_value is None:
        return
    if not versions_equal(review_value, comparison_value):
        raise ValueError(
            f"Item review and comparison describe different {label}: "
            f"{review_value!r} vs {comparison_value!r}."
        )


def build_dataset_concept_validation(
    item_review: ItemReview | pl.DataFrame,
    comparison: RICUComparisonResult | ComparisonEvidence | None = None,
    *,
    not_comparable_concepts: Mapping[str, str] | None = None,
) -> pl.DataFrame:
    """Dataset x concept validation status for one dataset.

    ``item_review`` is an :class:`~weavehr_yaib.item_review.ItemReview` or its
    summary table (e.g. ``item_review_summary.csv``). ``comparison`` is the
    in-memory comparison result or :func:`read_comparison_evidence`; ``None``
    means no comparison was run. ``not_comparable_concepts`` maps RICU concept
    names to the reason a direct comparison is not meaningful (``R!``).

    Raises ``ValueError`` when the item review and the comparison describe
    different dataset versions or RICU sources.
    """
    summary = item_review.summary if isinstance(item_review, ItemReview) else item_review
    rows = summary.to_dicts()
    declared = dict(not_comparable_concepts or {})
    unknown = set(declared) - {r["ricu_concept"] for r in rows}
    if unknown:
        raise ValueError(f"not_comparable_concepts names unknown concepts: {sorted(unknown)}")

    weavehr_version = _as_str(_single((r["weavehr_dataset_version"] for r in rows), "version"))
    reference_version = _as_str(
        _single((r["reference_dataset_version"] for r in rows), "reference version")
    )
    reference_source = _as_str(_single((r.get("reference_source") for r in rows), "source"))

    validation_level: str | None = None
    comparison_scope: str | None = None
    compared: dict[str, bool] | None = None
    if comparison is not None:
        evidence = (
            ComparisonEvidence.from_result(comparison)
            if isinstance(comparison, RICUComparisonResult)
            else comparison
        )
        if evidence.provenance.height != 1:
            raise ValueError("Comparison provenance must have exactly one row.")
        provenance = evidence.provenance.row(0, named=True)
        _check_consistent(
            "WeavEHR dataset versions",
            weavehr_version,
            _as_str(provenance.get("weavehr_dataset_version")),
        )
        _check_consistent(
            "reference dataset versions",
            reference_version,
            _as_str(provenance.get("reference_dataset_version")),
        )
        compared_source = _as_str(provenance.get("reference_dataset"))
        if reference_source and compared_source and reference_source != compared_source:
            raise ValueError(
                f"Item review and comparison describe different references: "
                f"{reference_source!r} vs {compared_source!r}."
            )
        weavehr_version = weavehr_version or _as_str(provenance.get("weavehr_dataset_version"))
        reference_version = reference_version or _as_str(
            provenance.get("reference_dataset_version")
        )
        validation_level = _as_str(provenance.get("validation_level"))
        comparison_scope = _as_str(provenance.get("comparison_scope"))
        compared = _compared_concepts(evidence.coverage)

    out: list[dict[str, object]] = []
    for row in rows:
        concept = row["ricu_concept"]
        defined = _as_bool(row["reference_concept_defined"])
        found = _as_bool(row["weavehr_concept_found"])
        coverage_compared = None if compared is None else compared.get(concept, False)

        status: RICUStatus | None
        if not defined:
            status, reason = None, "concept not defined in RICU for this source"
        elif concept in declared:
            status, reason = "R!", f"direct comparison not meaningful: {declared[concept]}"
        elif compared is None:
            status, reason = "R", "no comparison evidence"
        elif validation_level not in R_PLUS_VALIDATION_LEVELS:
            status, reason = "R", f"validation_level {validation_level} does not support R+"
        elif concept not in compared:
            status, reason = "R", "concept not in comparison coverage"
        elif not coverage_compared:
            status, reason = "R", "concept has no values on one side of the comparison coverage"
        else:
            status, reason = "R+", f"compared at validation_level {validation_level}"

        out.append(
            {
                "dataset": row["dataset"],
                "ricu_concept": concept,
                "weavehr_concept": _as_str(row["weavehr_concept"]),
                "reference_concept_defined": defined,
                "weavehr_concept_found": found,
                "validation_level": validation_level,
                "comparison_scope": comparison_scope,
                "coverage_compared": coverage_compared,
                "ricu_status": status,
                "reason": reason,
                "weavehr_dataset_version": weavehr_version,
                "reference_dataset_version": reference_version,
            }
        )
    return pl.DataFrame(out, schema=OUTPUT_SCHEMA)


def write_dataset_concept_validation(
    table: pl.DataFrame,
    out_dir: str | Path,
    *,
    formats: Iterable[Literal["csv", "parquet"]] = ("csv",),
) -> list[Path]:
    """Write ``dataset_concept_validation.{csv,parquet}`` to ``out_dir``."""
    formats = list(formats)
    unsupported = set(formats) - {"csv", "parquet"}
    if unsupported:
        raise ValueError(f"Unsupported formats {sorted(unsupported)}; use 'csv' or 'parquet'.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    table = table.select(OUTPUT_COLUMNS)
    paths: list[Path] = []
    for fmt in formats:
        path = out / f"{OUTPUT_NAME}.{fmt}"
        if fmt == "csv":
            table.write_csv(path)
        else:
            table.write_parquet(path)
        paths.append(path)
    return paths


__all__ = [
    "R_PLUS_VALIDATION_LEVELS",
    "ComparisonEvidence",
    "build_dataset_concept_validation",
    "read_comparison_evidence",
    "write_dataset_concept_validation",
]
