"""Item-level review of WeavEHR vs reference (RICU) concept definitions.

For every concept the review lists the source items (e.g. MIMIC-IV itemids,
OMOP concept_ids) that WeavEHR actually used and the items the reference
defines, and states on which basis they were matched. It is meant for review
by a medical expert, especially across dataset versions: an item only present
in WeavEHR is not an error per se (it may be legitimate coverage of a newer
version), and a reference item may itself be questionable. Reviewer columns
are left empty and are preserved when the review is regenerated.

Identifiers are only matched when both sides use an explicitly declared common
identifier space, or when a crosswalk is supplied. Nothing is inferred from
dataset names, labels or descriptions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import polars as pl

from .concepts import DYNAMIC_VARS, RICU_TO_WEAVEHR
from .io import filter_dataset_version, find_concept_file, mapped_concept_files
from .versions import (
    VersionComparison,
    relationship_from_counts,
    resolve_reference_version,
    resolve_weavehr_version,
    scope_label,
)
from .workflow import dataset_ricu_code, default_dataset_paths

ComparisonBasis = Literal["direct_identifier_match", "crosswalk", "side_by_side_only"]
ComparisonConfidence = Literal["high", "medium", "not_comparable"]
ItemStatus = Literal["shared", "weavehr_only", "reference_only", "not_directly_comparable"]

# Suggested values for the ``review_verdict`` column. ``accept`` on a
# weavehr_only item accepts additional WeavEHR coverage; the *_reference values
# flag reference mappings.
REVIEW_VERDICTS = (
    "accept",
    "reject",
    "questionable_reference",
    "incorrect_reference",
    "needs_discussion",
)
REVIEW_COLUMNS = ("review_verdict", "review_comment", "reviewer")

SOURCE_CODE_COLUMN = "source_code"

# What item statuses compare: WeavEHR items seen in the concept data against
# items configured in RICU's concept-dict.json. Data occurrence on the RICU side
# and WeavEHR's mapping configuration are reported separately where available.
ITEM_SET_BASIS = "weavehr_observed_vs_reference_configured"


@dataclass(frozen=True)
class IdentifierSpace:
    """A named identifier space and how to read its ids from WeavEHR codes."""

    name: str
    # Regex with one group extracting the id from a WeavEHR ``source_code``
    # (``EVENT//<id>//<label>//<unit>`` for the tables listed here).
    pattern: str | None = None


# Declared identifier spaces. Add an entry only when the identifier semantics
# are known; datasets without one are reviewed side by side.
WEAVEHR_IDENTIFIER_SPACES: dict[str, IdentifierSpace] = {
    # chartevents/labevents/outputevents/inputevents: EVENT//itemid//label//unit
    "mimic-iv": IdentifierSpace("mimic-iv:itemid", r"^[A-Z_]+//(\d+)//"),
    # OMOP measurement: MEASUREMENT//measurement_concept_id//source_value//unit
    "aumc": IdentifierSpace("omop:concept_id", r"^[A-Z_]+//(\d+)//"),
}
REFERENCE_IDENTIFIER_SPACES: dict[str, str] = {
    "miiv": "mimic-iv:itemid",
    # RICU reads native AmsterdamUMCdb item ids, not OMOP concept_ids.
    "aumc": "aumcdb:itemid",
}

MISSING_SOURCE_CODE_HINT = (
    "Item-level review needs the original source code of every concept row. Keep it in the "
    "WeavEHR concept outputs via the concept step config:\n"
    "  mapping_configs:\n"
    "    - name: <dataset>\n"
    "      version: <version>\n"
    "      extension_columns:\n"
    '        source_code: col("code")\n'
    '        dataset_version: col("version")'
)


@dataclass(frozen=True)
class ItemReview:
    items: pl.DataFrame
    summary: pl.DataFrame
    versions: VersionComparison


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def load_crosswalk(crosswalk: str | Path | pl.DataFrame | None) -> dict[str, set[str]] | None:
    """Read a reference-item -> WeavEHR-item crosswalk.

    Expects columns ``reference_item_id`` and ``weavehr_item_id`` (e.g. native
    AmsterdamUMCdb itemid -> OMOP concept_id). Many-to-many rows are allowed.
    """
    if crosswalk is None:
        return None
    df = crosswalk if isinstance(crosswalk, pl.DataFrame) else pl.read_csv(crosswalk)
    missing = {"reference_item_id", "weavehr_item_id"} - set(df.columns)
    if missing:
        raise ValueError(f"Crosswalk is missing columns: {sorted(missing)}")
    mapping: dict[str, set[str]] = {}
    for ref_id, weavehr_id in df.select(
        pl.col("reference_item_id").cast(pl.String), pl.col("weavehr_item_id").cast(pl.String)
    ).iter_rows():
        if ref_id is not None and weavehr_id is not None:
            mapping.setdefault(ref_id, set()).add(weavehr_id)
    return mapping


def load_reference_observed_items(
    observed: str | Path | pl.DataFrame | None,
) -> dict[str, dict[str, int | None]] | None:
    """Items actually present in reference data, per RICU concept.

    Expects columns ``ricu_concept`` and ``item_id`` (optional ``n_rows``).
    ``None`` means reference data occurrence is unknown.
    """
    if observed is None:
        return None
    df = observed if isinstance(observed, pl.DataFrame) else pl.read_csv(observed)
    missing = {"ricu_concept", "item_id"} - set(df.columns)
    if missing:
        raise ValueError(f"Reference observed items are missing columns: {sorted(missing)}")
    n_rows = pl.col("n_rows").cast(pl.Int64) if "n_rows" in df.columns else pl.lit(None)
    result: dict[str, dict[str, int | None]] = {}
    for concept, item_id, n in df.select(
        pl.col("ricu_concept").cast(pl.String), pl.col("item_id").cast(pl.String), n_rows
    ).iter_rows():
        result.setdefault(concept, {})[item_id] = n
    return result


def _evidence(
    weavehr_observed: bool | None,
    weavehr_n_rows: int | None,
    reference_configured: bool | None,
    reference_observed: bool | None,
) -> str:
    """Plain-language statement of what is known about one item."""
    parts = []
    if weavehr_observed is True:
        parts.append(f"observed in WeavEHR data ({weavehr_n_rows} rows)")
    elif weavehr_observed is False:
        parts.append("not observed in WeavEHR data")
    if reference_configured is True:
        parts.append("configured in RICU concept-dict")
    elif reference_configured is False:
        parts.append("not configured in RICU")
    if reference_observed is True:
        parts.append("observed in RICU data")
    elif reference_observed is False:
        parts.append("not observed in RICU data")
    elif reference_configured:
        parts.append("RICU data occurrence unknown")
    return "; ".join(parts)


def weavehr_items(
    concept_file: Path, *, dataset_version: str | None, space: IdentifierSpace | None
) -> pl.DataFrame:
    """Items observed in one WeavEHR concept parquet, one row per item id."""
    lf = pl.scan_parquet(concept_file)
    names = lf.collect_schema().names()
    if SOURCE_CODE_COLUMN not in names:
        raise ValueError(
            f"{concept_file} has no {SOURCE_CODE_COLUMN!r} column.\n{MISSING_SOURCE_CODE_HINT}"
        )
    lf = filter_dataset_version(lf, dataset_version)
    table = pl.col("table").cast(pl.String) if "table" in names else pl.lit(None, dtype=pl.String)
    codes = (
        lf.group_by(pl.col(SOURCE_CODE_COLUMN).cast(pl.String), table.alias("item_table"))
        .agg(pl.len().alias("weavehr_n_rows"))
        .collect()
    )
    pattern = space.pattern if space is not None else None
    parsed = (
        pl.col(SOURCE_CODE_COLUMN).str.extract(pattern, 1)
        if pattern
        else pl.lit(None, dtype=pl.String)
    )
    codes = codes.with_columns(
        parsed.alias("parsed_id"),
        pl.col(SOURCE_CODE_COLUMN).str.split("//").list.slice(2).list.join("//").alias("label"),
    ).with_columns(
        # Unparsed codes are kept under their full source code, never matched.
        pl.coalesce("parsed_id", SOURCE_CODE_COLUMN).alias("item_id"),
        pl.col("parsed_id").is_not_null().alias("id_parsed"),
    )
    return (
        codes.group_by("item_id", "id_parsed")
        .agg(
            pl.col("label").unique().sort().str.join("; ").alias("item_label"),
            pl.col("item_table").drop_nulls().unique().sort().str.join("; ").alias("item_table"),
            pl.col(SOURCE_CODE_COLUMN).unique().sort().str.join("; ").alias("weavehr_source_codes"),
            pl.col("weavehr_n_rows").sum(),
        )
        .sort("item_id")
    )


def reference_items(concept_dict: dict, ricu_name: str, ricu_source: str) -> list[dict[str, str]]:
    """Items a RICU concept defines for one source, from ``concept-dict.json``."""
    entries = concept_dict.get(ricu_name, {}).get("sources", {}).get(ricu_source) or []
    items = []
    for entry in entries:
        table = entry.get("table")
        detail = {k: v for k, v in entry.items() if k not in {"ids", "table"}}
        detail_text = json.dumps(detail, sort_keys=True) if detail else ""
        if "ids" in entry:
            ids = entry["ids"] if isinstance(entry["ids"], list) else [entry["ids"]]
            for item_id in ids:
                items.append(
                    {
                        "item_id": str(item_id),
                        "item_table": table or "",
                        "item_label": f"{table}.{entry.get('sub_var', '')}" if table else "",
                        "reference_detail": detail_text,
                    }
                )
        else:
            # Column items (``val_var``) and function items have no item id.
            key = entry.get("val_var") or f"{entry.get('class', 'item')}:{table}"
            items.append(
                {
                    "item_id": str(key),
                    "item_table": table or "",
                    "item_label": f"{table}.{entry['val_var']}" if "val_var" in entry else "",
                    "reference_detail": detail_text,
                }
            )
    return items


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def comparison_basis(
    dataset: str, ricu_source: str, crosswalk: dict[str, set[str]] | None
) -> ComparisonBasis:
    """How WeavEHR and reference identifiers can be matched for this pair."""
    if crosswalk:
        return "crosswalk"
    weavehr_space = WEAVEHR_IDENTIFIER_SPACES.get(dataset.lower())
    reference_space = REFERENCE_IDENTIFIER_SPACES.get(ricu_source)
    if weavehr_space is not None and weavehr_space.name == reference_space:
        return "direct_identifier_match"
    return "side_by_side_only"


def _confidence(basis: ComparisonBasis, versions: VersionComparison) -> ComparisonConfidence:
    if basis == "side_by_side_only":
        return "not_comparable"
    if basis == "direct_identifier_match" and versions.full_scope:
        return "high"
    return "medium"


def _concept_rows(
    *,
    weavehr: pl.DataFrame,
    reference: list[dict[str, str]],
    basis: ComparisonBasis,
    crosswalk: dict[str, set[str]] | None,
    reference_observed: dict[str, int | None] | None = None,
) -> tuple[list[dict[str, object]], str, dict[str, int | None]]:
    """Item rows, relationship and counts for one concept.

    Evidence flags describe the item's own identifier: ``weavehr_observed``
    (present in WeavEHR concept data), ``reference_configured`` (in RICU's
    concept-dict) and ``reference_observed`` (in RICU data; ``None`` when
    unknown). Flags about the other side are ``None`` unless both sides share
    the identifier space. ``weavehr_configured`` is always ``None``: WeavEHR
    mapping configurations are not evaluated item by item.
    """
    rows: list[dict[str, object]] = []
    w_rows = weavehr.to_dicts()
    w_ids = {r["item_id"] for r in w_rows if r["id_parsed"]}
    r_ids = {r["item_id"] for r in reference}
    direct = basis == "direct_identifier_match"

    def ref_observed(item_id: str) -> tuple[bool | None, int | None]:
        if reference_observed is None:
            return None, None
        return item_id in reference_observed, reference_observed.get(item_id)

    def flags(
        weavehr_observed: bool | None,
        weavehr_n_rows: int | None,
        reference_configured: bool | None,
        item_id: str,
    ) -> dict[str, object]:
        observed, n_ref = (
            ref_observed(item_id) if reference_configured is not None else (None, None)
        )
        return {
            "weavehr_observed": weavehr_observed,
            "weavehr_configured": None,
            "reference_configured": reference_configured,
            "reference_observed": observed,
            "reference_n_rows": n_ref,
            "evidence": _evidence(weavehr_observed, weavehr_n_rows, reference_configured, observed),
        }

    def status_weavehr(row: dict) -> tuple[ItemStatus, list[str]]:
        if basis == "side_by_side_only" or not row["id_parsed"]:
            return "not_directly_comparable", []
        if basis == "direct_identifier_match":
            return ("shared" if row["item_id"] in r_ids else "weavehr_only"), []
        assert crosswalk is not None
        mapped_from = sorted(r for r in r_ids if row["item_id"] in crosswalk.get(r, set()))
        if mapped_from:
            return "shared", mapped_from
        known_targets = set().union(*crosswalk.values())
        return (
            "weavehr_only" if row["item_id"] in known_targets else "not_directly_comparable"
        ), []

    def status_reference(item: dict) -> tuple[ItemStatus, list[str]]:
        if basis == "side_by_side_only":
            return "not_directly_comparable", []
        if basis == "direct_identifier_match":
            return ("shared" if item["item_id"] in w_ids else "reference_only"), []
        assert crosswalk is not None
        mapped = crosswalk.get(item["item_id"], set())
        if not mapped:
            return "not_directly_comparable", []
        hit = sorted(mapped & w_ids)
        return ("shared", hit) if hit else ("reference_only", sorted(mapped))

    reference_by_id = {r["item_id"]: r for r in reference}
    for row in w_rows:
        status, counterpart = status_weavehr(row)
        merged = basis == "direct_identifier_match" and status == "shared"
        ref = reference_by_id.get(row["item_id"], {}) if merged else {}
        rows.append(
            {
                "side": "both" if merged else "weavehr",
                "item_status": status,
                **flags(
                    True,
                    row["weavehr_n_rows"],
                    (row["item_id"] in r_ids) if direct else None,
                    row["item_id"],
                ),
                "item_id": row["item_id"],
                "item_label": row["item_label"],
                "item_table": row["item_table"],
                "weavehr_source_codes": row["weavehr_source_codes"],
                "weavehr_n_rows": row["weavehr_n_rows"],
                "reference_detail": ref.get("reference_detail", ""),
                "counterpart_item_ids": "; ".join(counterpart),
            }
        )
    for item in reference:
        status, counterpart = status_reference(item)
        if basis == "direct_identifier_match" and status == "shared":
            continue  # already listed once with side == "both"
        rows.append(
            {
                "side": "reference",
                "item_status": status,
                **flags(False if direct else None, None, True, item["item_id"]),
                "item_id": item["item_id"],
                "item_label": item["item_label"],
                "item_table": item["item_table"],
                "weavehr_source_codes": "",
                "weavehr_n_rows": None,
                "reference_detail": item["reference_detail"],
                "counterpart_item_ids": "; ".join(counterpart),
            }
        )

    statuses = [r["item_status"] for r in rows]
    observed_reference = (
        None if reference_observed is None else {i for i in r_ids if i in reference_observed}
    )
    counts: dict[str, int | None] = {
        "n_weavehr_observed_items": len(w_rows),
        "n_weavehr_observed_rows": int(sum(r["weavehr_n_rows"] for r in w_rows)),
        "n_weavehr_configured_items": None,
        "n_reference_configured_items": len(reference),
        "n_reference_observed_items": (
            None if observed_reference is None else len(observed_reference)
        ),
        "n_reference_configured_not_observed": (
            None if observed_reference is None else len(r_ids - observed_reference)
        ),
        "n_shared": sum(
            1 for r in rows if r["item_status"] == "shared" and r["side"] in {"both", "weavehr"}
        ),
        "n_weavehr_only": statuses.count("weavehr_only"),
        "n_reference_only": statuses.count("reference_only"),
        "n_not_directly_comparable": statuses.count("not_directly_comparable"),
    }
    if basis == "side_by_side_only":
        relationship = "not_directly_comparable"
    elif basis == "direct_identifier_match":
        relationship = relationship_from_counts(len(w_ids), len(r_ids), len(w_ids & r_ids))
    else:
        assert crosswalk is not None
        mapped_reference = (
            set().union(*(crosswalk.get(r, set()) for r in r_ids)) if r_ids else set()
        )
        relationship = relationship_from_counts(
            len(w_ids), len(mapped_reference), len(w_ids & mapped_reference)
        )
    return rows, relationship, counts


def build_item_review(
    *,
    dataset: str,
    concept_root: str | Path,
    ricu_concept_dict: str | Path,
    versions: VersionComparison,
    ricu_source: str | None = None,
    dynamic_vars: list[str] | None = None,
    concept_mapping: dict[str, str] | None = None,
    concept_version: str | None = "1.0.0",
    crosswalk: str | Path | pl.DataFrame | None = None,
    reference_observed_items: str | Path | pl.DataFrame | None = None,
) -> ItemReview:
    """Build the per-item and per-concept review tables for one dataset.

    WeavEHR items are those observed in the concept data, reference items those
    configured in RICU's concept-dict (``item_set_basis``). Pass
    ``reference_observed_items`` (``ricu_concept``, ``item_id``, optional
    ``n_rows``) to also record which reference items occur in RICU data.
    """
    dataset = dataset.lower()
    ricu_source = ricu_source or dataset_ricu_code(dataset)
    mapping = concept_mapping or RICU_TO_WEAVEHR
    concept_dict = json.loads(Path(ricu_concept_dict).read_text())
    xwalk = load_crosswalk(crosswalk)
    ref_observed = load_reference_observed_items(reference_observed_items)
    basis = comparison_basis(dataset, ricu_source, xwalk)
    confidence = _confidence(basis, versions)
    space = WEAVEHR_IDENTIFIER_SPACES.get(dataset)

    context = {
        "dataset": dataset,
        "weavehr_dataset_version": versions.weavehr.version,
        "weavehr_version_source": versions.weavehr.source,
        "weavehr_version_verified": versions.weavehr.verified,
        "weavehr_representation": versions.weavehr.representation,
        "reference_source": f"ricu:{ricu_source}",
        "reference_dataset_version": versions.reference.version,
        "reference_version_source": versions.reference.source,
        "reference_version_verified": versions.reference.verified,
        "reference_representation": versions.reference.representation,
        "same_version": versions.same_version,
        "comparison_basis": basis,
        "comparison_confidence": confidence,
        "item_set_basis": ITEM_SET_BASIS,
        "reference_observation_available": ref_observed is not None,
    }
    empty_review = {c: "" for c in REVIEW_COLUMNS}

    item_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for ricu_name in dynamic_vars or DYNAMIC_VARS:
        weavehr_name = mapping.get(ricu_name)
        concept_file = (
            find_concept_file(concept_root, weavehr_name, dataset=dataset, version=concept_version)
            if weavehr_name
            else None
        )
        w_items = (
            weavehr_items(concept_file, dataset_version=versions.weavehr.version, space=space)
            if concept_file is not None
            else pl.DataFrame()
        )
        r_items = reference_items(concept_dict, ricu_name, ricu_source)
        rows, relationship, counts = _concept_rows(
            weavehr=w_items,
            reference=r_items,
            basis=basis,
            crosswalk=xwalk,
            reference_observed=None if ref_observed is None else ref_observed.get(ricu_name, {}),
        )
        names = {"ricu_concept": ricu_name, "weavehr_concept": weavehr_name}
        item_rows += [{**context, **names, **row, **empty_review} for row in rows]
        summary_rows.append(
            {
                **context,
                **names,
                "weavehr_concept_found": concept_file is not None,
                "reference_concept_defined": bool(r_items),
                **counts,
                "relationship": relationship,
                **empty_review,
            }
        )

    schema = {
        "weavehr_dataset_version": pl.String,
        "reference_dataset_version": pl.String,
        "weavehr_representation": pl.String,
        "reference_representation": pl.String,
        "same_version": pl.Boolean,
        "weavehr_concept": pl.String,
    }
    flag_schema = {
        "weavehr_observed": pl.Boolean,
        "weavehr_configured": pl.Boolean,
        "reference_configured": pl.Boolean,
        "reference_observed": pl.Boolean,
        "reference_n_rows": pl.Int64,
        "weavehr_n_rows": pl.Int64,
    }
    count_schema = {
        c: pl.Int64
        for c in (
            "n_weavehr_configured_items",
            "n_reference_observed_items",
            "n_reference_configured_not_observed",
        )
    }
    items = pl.DataFrame(item_rows, schema_overrides={**schema, **flag_schema})
    summary = pl.DataFrame(summary_rows, schema_overrides={**schema, **count_schema})
    return ItemReview(items=items, summary=summary, versions=versions)


def _carry_over_reviews(new: pl.DataFrame, path: Path, key: list[str]) -> pl.DataFrame:
    """Keep reviewer entries from an existing review CSV for matching rows."""
    if not path.is_file() or new.is_empty():
        return new
    old = pl.read_csv(path, infer_schema=False)
    if not set(key) | set(REVIEW_COLUMNS) <= set(old.columns):
        return new
    old = old.select([*key, *REVIEW_COLUMNS]).unique(subset=key, keep="last")
    merged = new.with_columns(pl.col(key).cast(pl.String)).join(
        old, on=key, how="left", suffix="_previous"
    )
    return merged.with_columns(
        [
            pl.coalesce(pl.col(f"{c}_previous"), pl.col(c).cast(pl.String)).fill_null("").alias(c)
            for c in REVIEW_COLUMNS
        ]
    ).drop([f"{c}_previous" for c in REVIEW_COLUMNS])


def write_item_review(review: ItemReview, out_dir: str | Path) -> tuple[Path, Path]:
    """Write ``item_review.csv`` and ``item_review_summary.csv``.

    Existing reviewer entries are carried over by ``(ricu_concept, side,
    item_id)`` for items and by ``ricu_concept`` for the summary.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    items_path = out / "item_review.csv"
    summary_path = out / "item_review_summary.csv"
    _carry_over_reviews(review.items, items_path, ["ricu_concept", "side", "item_id"]).write_csv(
        items_path
    )
    _carry_over_reviews(review.summary, summary_path, ["ricu_concept"]).write_csv(summary_path)
    return items_path, summary_path


def write_item_review_for_dataset(
    *,
    dataset: str,
    concept_root: str | Path,
    ricu_concept_dict: str | Path,
    output_root: str | Path | None = None,
    dataset_version: str | None = None,
    reference_version: str | None = None,
    crosswalk: str | Path | pl.DataFrame | None = None,
    dynamic_vars: list[str] | None = None,
    concept_mapping: dict[str, str] | None = None,
    concept_version: str | None = "1.0.0",
    reference_observed_items: str | Path | pl.DataFrame | None = None,
) -> tuple[ItemReview, Path, Path]:
    """Resolve versions, build and write the item review for a dataset.

    Output goes to ``<output_root>/item_review/weavehr-<v>__ricu-<source>-<v>/``.
    The reference version is taken from the RICU export's provenance file in
    ``output_root`` when present.
    """
    paths = default_dataset_paths(
        dataset=dataset,
        output_root=output_root,
        concept_root=concept_root,
        ricu_concept_dict=ricu_concept_dict,
    )
    vars_ = dynamic_vars or DYNAMIC_VARS
    mapping = concept_mapping or RICU_TO_WEAVEHR
    weavehr = resolve_weavehr_version(
        dataset=paths.dataset,
        concept_files=mapped_concept_files(
            paths.concept_root,
            dataset=paths.dataset,
            version=concept_version,
            dynamic_vars=vars_,
            concept_mapping=mapping,
        ),
        workspace=paths.concept_root.parent,
        dataset_version=dataset_version,
    )
    ricu_source = dataset_ricu_code(paths.dataset)
    reference = resolve_reference_version(
        ricu_source=ricu_source,
        reference_data_path=paths.ricu_dynamic_path,
        reference_version=reference_version,
    )
    versions = VersionComparison(weavehr=weavehr, reference=reference)
    review = build_item_review(
        dataset=paths.dataset,
        concept_root=paths.concept_root,
        ricu_concept_dict=paths.ricu_concept_dict,
        versions=versions,
        ricu_source=ricu_source,
        dynamic_vars=vars_,
        concept_mapping=mapping,
        concept_version=concept_version,
        crosswalk=crosswalk,
        reference_observed_items=reference_observed_items,
    )
    out_dir = paths.output_root / "item_review" / scope_label(versions, ricu_source)
    items_path, summary_path = write_item_review(review, out_dir)
    return review, items_path, summary_path


__all__ = [
    "REVIEW_VERDICTS",
    "ItemReview",
    "build_item_review",
    "comparison_basis",
    "load_crosswalk",
    "write_item_review",
    "write_item_review_for_dataset",
]
