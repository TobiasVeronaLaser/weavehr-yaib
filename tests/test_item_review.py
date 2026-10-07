"""Item-level review: identifier spaces, crosswalks, provenance, reviewer columns."""

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from weavehr_yaib.item_review import (
    build_item_review,
    comparison_basis,
    write_item_review,
    write_item_review_for_dataset,
)
from weavehr_yaib.versions import DatasetVersion, VersionComparison


def _concept(root: Path, dataset: str, codes: list[str], **extra: list[str]) -> None:
    path = root / "heart_rate/1.0.0" / f"{dataset}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(codes)
    pl.DataFrame(
        {
            "subject_id": list(range(n)),
            "time": pl.Series([datetime(2020, 1, 1)] * n, dtype=pl.Datetime("us")),
            "code": ["heart_rate//bpm"] * n,
            "numeric_value": pl.Series([80.0] * n, dtype=pl.Float32),
            "table": ["measurement"] * n,
            **extra,
            **({"source_code": codes} if codes else {}),
        }
    ).write_parquet(path)


def _concept_dict(path: Path, source: str, ids: list[int]) -> Path:
    path.write_text(
        json.dumps({"hr": {"sources": {source: [{"ids": ids, "table": "t", "sub_var": "itemid"}]}}})
    )
    return path


def _versions(dataset: str, weavehr: tuple, reference: tuple) -> VersionComparison:
    return VersionComparison(
        weavehr=DatasetVersion(dataset, *weavehr),
        reference=DatasetVersion("ricu:x", *reference),
    )


def _items(review) -> dict[tuple[str, str], dict]:
    return {(r["side"], r["item_id"]): r for r in review.items.iter_rows(named=True)}


def test_identifier_spaces_are_declared_not_inferred_from_names() -> None:
    assert comparison_basis("mimic-iv", "miiv", None) == "direct_identifier_match"
    # MIMIC-III and MIMIC-IV are not assumed to share item identifiers.
    assert comparison_basis("mimic-iv", "mimic", None) == "side_by_side_only"
    assert comparison_basis("mimic-iii", "mimic", None) == "side_by_side_only"
    # AUMC: OMOP concept_ids (WeavEHR) vs native itemids (RICU).
    assert comparison_basis("aumc", "aumc", None) == "side_by_side_only"
    assert comparison_basis("aumc", "aumc", {"6640": {"3027018"}}) == "crosswalk"


def test_mimic_iv_direct_match_across_versions(tmp_path: Path) -> None:
    _concept(
        tmp_path,
        "mimic-iv",
        [
            "CHART//220045//Heart Rate//bpm",
            "CHART//220045//Heart Rate//bpm",
            "CHART//999//New//bpm",
        ],
        dataset_version=["3.1"] * 3,
    )
    review = build_item_review(
        dataset="mimic-iv",
        concept_root=tmp_path,
        ricu_concept_dict=_concept_dict(tmp_path / "cd.json", "miiv", [220045, 220046]),
        versions=_versions("mimic-iv", ("3.1", "explicit"), ("2.2", "provenance_file")),
        dynamic_vars=["hr"],
    )
    items = _items(review)
    assert items[("both", "220045")]["item_status"] == "shared"
    assert items[("both", "220045")]["weavehr_n_rows"] == 2
    assert items[("both", "220045")]["item_label"] == "Heart Rate//bpm"
    # Additional WeavEHR coverage is reported, not labelled an error.
    assert items[("weavehr", "999")]["item_status"] == "weavehr_only"
    assert items[("reference", "220046")]["item_status"] == "reference_only"

    row = review.summary.row(0, named=True)
    assert row["comparison_basis"] == "direct_identifier_match"
    assert row["comparison_confidence"] == "medium"  # versions differ
    assert row["relationship"] == "partial_overlap"
    assert (row["weavehr_dataset_version"], row["reference_dataset_version"]) == ("3.1", "2.2")
    assert row["same_version"] is False
    assert {row["review_verdict"], row["review_comment"], row["reviewer"]} == {""}

    same = build_item_review(
        dataset="mimic-iv",
        concept_root=tmp_path,
        ricu_concept_dict=tmp_path / "cd.json",
        versions=_versions("mimic-iv", ("3.1", "explicit"), ("3.1", "provenance_file")),
        dynamic_vars=["hr"],
    )
    assert same.summary["comparison_confidence"].to_list() == ["high"]


def test_aumc_without_crosswalk_lists_both_sides_side_by_side(tmp_path: Path) -> None:
    _concept(tmp_path, "aumc", ["MEASUREMENT//3027018//Hartfrequentie///min"])
    review = build_item_review(
        dataset="aumc",
        concept_root=tmp_path,
        ricu_concept_dict=_concept_dict(tmp_path / "cd.json", "aumc", [6640]),
        versions=_versions("aumc", ("1.5.0", "extraction_dirs"), ("1.0.2", "manual_default")),
        dynamic_vars=["hr"],
    )
    items = _items(review)
    assert set(items) == {("weavehr", "3027018"), ("reference", "6640")}
    assert {r["item_status"] for r in items.values()} == {"not_directly_comparable"}
    assert {r["comparison_basis"] for r in items.values()} == {"side_by_side_only"}
    assert {r["comparison_confidence"] for r in items.values()} == {"not_comparable"}
    assert items[("weavehr", "3027018")]["item_label"] == "Hartfrequentie///min"
    row = review.summary.row(0, named=True)
    assert row["relationship"] == "not_directly_comparable"
    assert row["reference_version_source"] == "manual_default"
    assert row["reference_version_verified"] is False


def test_aumc_with_crosswalk(tmp_path: Path) -> None:
    _concept(
        tmp_path,
        "aumc",
        ["MEASUREMENT//3027018//Hartfrequentie///min", "MEASUREMENT//21490872//HF EKG///min"],
    )
    crosswalk = pl.DataFrame(
        {"reference_item_id": [6640, 9999], "weavehr_item_id": [3027018, 21490872]}
    )
    review = build_item_review(
        dataset="aumc",
        concept_root=tmp_path,
        ricu_concept_dict=_concept_dict(tmp_path / "cd.json", "aumc", [6640]),
        versions=_versions("aumc", ("1.5.0", "explicit"), ("1.0.2", "explicit")),
        dynamic_vars=["hr"],
        crosswalk=crosswalk,
    )
    items = _items(review)
    assert items[("weavehr", "3027018")]["item_status"] == "shared"
    assert items[("weavehr", "3027018")]["counterpart_item_ids"] == "6640"
    assert items[("reference", "6640")]["item_status"] == "shared"
    assert items[("weavehr", "21490872")]["item_status"] == "weavehr_only"
    row = review.summary.row(0, named=True)
    assert (row["comparison_basis"], row["comparison_confidence"]) == ("crosswalk", "medium")
    assert row["relationship"] == "weavehr_superset"


def test_missing_source_code_fails_with_configuration_hint(tmp_path: Path) -> None:
    _concept(tmp_path, "aumc", [])
    with pytest.raises(ValueError, match='source_code: col\\("code"\\)'):
        build_item_review(
            dataset="aumc",
            concept_root=tmp_path,
            ricu_concept_dict=_concept_dict(tmp_path / "cd.json", "aumc", [6640]),
            versions=_versions("aumc", ("1.5.0", "explicit"), ("1.0.2", "manual_default")),
            dynamic_vars=["hr"],
        )


def test_reviewer_entries_survive_regeneration(tmp_path: Path) -> None:
    concept_root = tmp_path / "project/workspace/concept"
    _concept(concept_root, "aumc", ["MEASUREMENT//3027018//Hartfrequentie///min"])
    concept_dict = _concept_dict(tmp_path / "cd.json", "aumc", [6640])

    def run():
        return write_item_review_for_dataset(
            dataset="aumc",
            concept_root=concept_root,
            ricu_concept_dict=concept_dict,
            output_root=tmp_path / "out",
            dataset_version="1.5.0",
            dynamic_vars=["hr"],
        )

    review, items_path, summary_path = run()
    assert items_path.parent.name == "weavehr-1.5.0__ricu-aumc-1.0.2"
    summary = review.summary.row(0, named=True)
    assert summary["weavehr_representation"] == "OMOP CDM 5.4 (AMSTEL ETL)"
    assert summary["reference_representation"] == "native source tables (ricu)"

    items = pl.read_csv(items_path, infer_schema=False).with_columns(
        pl.when(pl.col("item_id") == "6640")
        .then(pl.lit("questionable_reference"))
        .otherwise(pl.col("review_verdict"))
        .alias("review_verdict"),
        pl.when(pl.col("item_id") == "3027018")
        .then(pl.lit("newer AUMC item, plausible"))
        .otherwise(pl.col("review_comment"))
        .alias("review_comment"),
    )
    items.write_csv(items_path)

    review, items_path, _ = run()
    reread = {
        r["item_id"]: r for r in pl.read_csv(items_path, infer_schema=False).iter_rows(named=True)
    }
    assert reread["6640"]["review_verdict"] == "questionable_reference"
    assert reread["3027018"]["review_comment"] == "newer AUMC item, plausible"

    # Writing the in-memory review again keeps the same entries.
    write_item_review(review, items_path.parent)
    assert (
        pl.read_csv(items_path, infer_schema=False)["review_verdict"]
        .to_list()
        .count("questionable_reference")
        == 1
    )


# ---------------------------------------------------------------------------
# Configured vs observed evidence
# ---------------------------------------------------------------------------


def _mimic_review(tmp_path: Path, reference_observed_items=None):
    _concept(
        tmp_path,
        "mimic-iv",
        [
            "CHART//220045//Heart Rate//bpm",
            "CHART//220045//Heart Rate//bpm",
            "CHART//999//New//bpm",
        ],
        dataset_version=["3.1"] * 3,
    )
    return build_item_review(
        dataset="mimic-iv",
        concept_root=tmp_path,
        ricu_concept_dict=_concept_dict(tmp_path / "cd.json", "miiv", [220045, 220046]),
        versions=_versions("mimic-iv", ("3.1", "explicit"), ("2.2", "provenance_file")),
        dynamic_vars=["hr"],
        reference_observed_items=reference_observed_items,
    )


def test_item_evidence_separates_observed_and_configured(tmp_path: Path) -> None:
    review = _mimic_review(tmp_path)
    items = _items(review)

    shared = items[("both", "220045")]
    assert (shared["weavehr_observed"], shared["reference_configured"]) == (True, True)
    # RICU data occurrence is unknown, not assumed.
    assert shared["reference_observed"] is None
    assert "RICU data occurrence unknown" in shared["evidence"]

    assert items[("weavehr", "999")]["reference_configured"] is False
    reference_only = items[("reference", "220046")]
    assert (reference_only["weavehr_observed"], reference_only["reference_configured"]) == (
        False,
        True,
    )
    assert reference_only["reference_observed"] is None
    # WeavEHR mapping configuration is not evaluated per item.
    assert review.items["weavehr_configured"].null_count() == review.items.height
    assert set(review.items["item_set_basis"]) == {"weavehr_observed_vs_reference_configured"}

    row = review.summary.row(0, named=True)
    assert (row["n_weavehr_observed_items"], row["n_weavehr_observed_rows"]) == (2, 3)
    assert row["n_reference_configured_items"] == 2
    assert row["n_reference_observed_items"] is None
    assert row["n_reference_configured_not_observed"] is None
    assert row["reference_observation_available"] is False


def test_configured_but_unobserved_reference_item_is_not_shown_as_observed(
    tmp_path: Path,
) -> None:
    observed = pl.DataFrame({"ricu_concept": ["hr"], "item_id": [220045], "n_rows": [10]})
    review = _mimic_review(tmp_path, reference_observed_items=observed)
    items = _items(review)

    assert items[("both", "220045")]["reference_observed"] is True
    assert items[("both", "220045")]["reference_n_rows"] == 10
    unobserved = items[("reference", "220046")]
    assert (unobserved["reference_configured"], unobserved["reference_observed"]) == (True, False)
    assert "not observed in RICU data" in unobserved["evidence"]

    row = review.summary.row(0, named=True)
    assert row["reference_observation_available"] is True
    assert (row["n_reference_observed_items"], row["n_reference_configured_not_observed"]) == (1, 1)


def test_side_by_side_flags_do_not_cross_identifier_spaces(tmp_path: Path) -> None:
    _concept(tmp_path, "aumc", ["MEASUREMENT//3027018//Hartfrequentie///min"])
    review = build_item_review(
        dataset="aumc",
        concept_root=tmp_path,
        ricu_concept_dict=_concept_dict(tmp_path / "cd.json", "aumc", [6640]),
        versions=_versions("aumc", ("1.5.0", "extraction_dirs"), ("1.0.2", "manual_default")),
        dynamic_vars=["hr"],
    )
    items = _items(review)
    weavehr = items[("weavehr", "3027018")]
    assert (weavehr["weavehr_observed"], weavehr["reference_configured"]) == (True, None)
    reference = items[("reference", "6640")]
    assert (reference["weavehr_observed"], reference["reference_configured"]) == (None, True)
