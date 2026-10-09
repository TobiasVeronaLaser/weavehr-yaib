"""Dataset x concept RICU validation status (R / R+ / R!) from existing evidence."""

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from weavehr_yaib.dataset_concept_validation import (
    ComparisonEvidence,
    build_dataset_concept_validation,
    read_comparison_evidence,
    write_dataset_concept_validation,
)
from weavehr_yaib.item_review import build_item_review, write_item_review
from weavehr_yaib.stay_ids import StayIdComparison, load_stay_crosswalk
from weavehr_yaib.versions import DatasetVersion, VersionComparison
from weavehr_yaib.workflow import compare_weavehr_wide_to_ricu

# hr, map: in WeavEHR and RICU data; resp: RICU data only; glu: not defined in RICU.
VARS = ["hr", "map", "resp", "glu"]
MAPPING = {"hr": "heart_rate", "map": "mean_bp", "resp": "resp_rate", "glu": "glucose"}
MIIV_STAY_SPACE = "mimic-iv:icustays.stay_id"
MIIV_STAYS = StayIdComparison(MIIV_STAY_SPACE, MIIV_STAY_SPACE)
SAME = (("2.2", "extraction_dirs"), ("2.2", "provenance_file"))
CROSS = (("3.1", "explicit"), ("2.2", "provenance_file"))
UNVERIFIED = (("2.2", "explicit"), ("2.2", "ricu_config"))


def _versions(dataset: str, ricu_source: str, weavehr: tuple, reference: tuple):
    return VersionComparison(
        weavehr=DatasetVersion(dataset, *weavehr),
        reference=DatasetVersion(f"ricu:{ricu_source}", *reference),
    )


def _concepts(root: Path, dataset: str, version: str, code: str) -> None:
    for name in ("heart_rate", "mean_bp", "glucose"):
        path = root / name / "1.0.0" / f"{dataset}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(
            {
                "subject_id": [1],
                "time": pl.Series([datetime(2020, 1, 1)], dtype=pl.Datetime("us")),
                "numeric_value": [80.0],
                "source_code": [code],
                "dataset_version": [version],
            }
        ).write_parquet(path)


def _concept_dict(path: Path, source: str) -> Path:
    entry = [{"ids": [1], "table": "t", "sub_var": "itemid"}]
    path.write_text(json.dumps({c: {"sources": {source: entry}} for c in ("hr", "map", "resp")}))
    return path


def _review(tmp_path: Path, versions: VersionComparison, dataset="mimic-iv", source="miiv"):
    root = tmp_path / "concepts"
    _concepts(root, dataset, versions.weavehr.version, "CHART//1//x//y")
    return build_item_review(
        dataset=dataset,
        concept_root=root,
        ricu_concept_dict=_concept_dict(tmp_path / "cd.json", source),
        versions=versions,
        ricu_source=source,
        dynamic_vars=VARS,
        concept_mapping=MAPPING,
    )


def _wide(stays: list[int], cols: dict[str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "stay_id": [s for s in stays for _ in range(3)],
            "time": [t for _ in stays for t in range(3)],
            **{c: [v] * (3 * len(stays)) for c, v in cols.items()},
        }
    )


def _compare(tmp_path: Path, versions, stay_ids=MIIV_STAYS, weavehr_stays=(1, 2), **kwargs):
    files = {
        "wide": tmp_path / "weavehr_dyn_168h.parquet",
        "reference": tmp_path / "ricu_dynamic.parquet",
        "windows": tmp_path / "ricu_windows.parquet",
    }
    _wide(list(weavehr_stays), {"hr": 80.0, "map": 70.0}).write_parquet(files["wide"])
    _wide([1, 2], {"hr": 80.0, "map": 70.0, "resp": 16.0}).write_parquet(files["reference"])
    pl.DataFrame({"stay_id": [1, 2], "start": [0.0] * 2, "end": [2.0] * 2}).write_parquet(
        files["windows"]
    )
    return compare_weavehr_wide_to_ricu(
        weavehr_wide_path=files["wide"],
        ricu_dynamic_path=files["reference"],
        ricu_stay_windows_path=files["windows"],
        dynamic_vars=VARS,
        versions=versions,
        stay_ids=stay_ids,
        **kwargs,
    )


def _status(table: pl.DataFrame) -> dict[str, str | None]:
    return dict(table.select("ricu_concept", "ricu_status").iter_rows())


def _by_concept(table: pl.DataFrame) -> dict[str, dict]:
    return {r["ricu_concept"]: r for r in table.iter_rows(named=True)}


def test_without_comparison_defined_concepts_are_plain_r(tmp_path: Path) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    table = build_dataset_concept_validation(_review(tmp_path, versions))

    assert _status(table) == {"hr": "R", "map": "R", "resp": "R", "glu": None}
    rows = _by_concept(table)
    assert rows["hr"]["reason"] == "no comparison evidence"
    assert rows["hr"]["coverage_compared"] is None
    assert rows["hr"]["validation_level"] is None
    # Not run is not "not meaningful": no R! without an explicit declaration.
    assert "R!" not in _status(table).values()
    assert table.columns == [
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
    ]


def test_concept_absent_from_ricu_gets_no_status(tmp_path: Path) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    table = build_dataset_concept_validation(
        _review(tmp_path, versions), _compare(tmp_path, versions)
    )
    glu = _by_concept(table)["glu"]
    assert glu["reference_concept_defined"] is False
    assert glu["weavehr_concept_found"] is True
    assert glu["ricu_status"] is None
    assert glu["reason"] == "concept not defined in RICU for this source"


def test_full_same_version_gives_r_plus_for_compared_concepts(tmp_path: Path) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    table = build_dataset_concept_validation(
        _review(tmp_path, versions), _compare(tmp_path, versions)
    )
    assert _status(table) == {"hr": "R+", "map": "R+", "resp": "R", "glu": None}
    rows = _by_concept(table)
    assert rows["hr"]["validation_level"] == "full_same_version"
    assert rows["hr"]["comparison_scope"] == "full"
    assert rows["hr"]["coverage_compared"] is True
    # resp is defined in RICU but WeavEHR has no data for it: missing evidence.
    assert rows["resp"]["coverage_compared"] is False
    assert rows["resp"]["weavehr_concept_found"] is False
    assert rows["resp"]["reason"] == "concept not in comparison coverage"
    assert (rows["hr"]["weavehr_dataset_version"], rows["hr"]["reference_dataset_version"]) == (
        "2.2",
        "2.2",
    )


def test_shared_subset_stay_crosswalk_gives_r_plus(tmp_path: Path) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    stay_ids = StayIdComparison(
        "omop:visit_occurrence.visit_occurrence_id",
        "aumcdb:admissions.admissionid",
        crosswalk=load_stay_crosswalk(
            pl.DataFrame({"reference_stay_id": [1, 2], "weavehr_stay_id": [2, 1]})
        ),
    )
    comparison = _compare(tmp_path, versions, stay_ids=stay_ids)
    assert comparison.provenance["validation_level"].item() == "shared_subset_stay_crosswalk"

    table = build_dataset_concept_validation(_review(tmp_path, versions), comparison)
    assert _status(table) == {"hr": "R+", "map": "R+", "resp": "R", "glu": None}


@pytest.mark.parametrize(
    ("pair", "level"),
    [
        (CROSS, "shared_subset_cross_version"),
        (UNVERIFIED, "shared_subset_unverified_version"),
    ],
)
def test_no_r_plus_without_same_verified_version(tmp_path: Path, pair, level) -> None:
    versions = _versions("mimic-iv", "miiv", *pair)
    comparison = _compare(tmp_path, versions)
    assert comparison.provenance["validation_level"].item() == level
    # The concepts are in coverage, but the comparison level does not support R+.
    assert set(comparison.coverage["concept"]) == {"hr", "map"}

    table = build_dataset_concept_validation(_review(tmp_path, versions), comparison)
    assert _status(table) == {"hr": "R", "map": "R", "resp": "R", "glu": None}
    hr = _by_concept(table)["hr"]
    assert hr["coverage_compared"] is True
    assert hr["reason"] == f"validation_level {level} does not support R+"


def test_dataset_not_comparable_is_neither_r_plus_nor_r_bang(tmp_path: Path) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    comparison = _compare(tmp_path, versions, weavehr_stays=(7, 8))
    assert comparison.provenance["validation_level"].item() == "not_comparable"

    table = build_dataset_concept_validation(_review(tmp_path, versions), comparison)
    assert _status(table) == {"hr": "R", "map": "R", "resp": "R", "glu": None}
    assert _by_concept(table)["hr"]["coverage_compared"] is False


def test_r_bang_only_from_explicit_concept_declaration(tmp_path: Path) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    table = build_dataset_concept_validation(
        _review(tmp_path, versions),
        _compare(tmp_path, versions),
        not_comparable_concepts={"resp": "different unit semantics", "glu": "n/a"},
    )
    # glu is not defined in RICU, so it cannot be R! either.
    assert _status(table) == {"hr": "R+", "map": "R+", "resp": "R!", "glu": None}
    assert _by_concept(table)["resp"]["reason"] == (
        "direct comparison not meaningful: different unit semantics"
    )
    with pytest.raises(ValueError, match="unknown concepts"):
        build_dataset_concept_validation(
            _review(tmp_path, versions), not_comparable_concepts={"nope": "x"}
        )


@pytest.mark.parametrize(
    "pair",
    [
        (("1.0.0", "extraction_dirs"), ("1.0.2", "manual_default")),  # as resolved today
        (("1.0.0", "explicit"), ("1.0.2", "explicit")),  # verified, cross-version
    ],
)
def test_aumc_cross_version_comparison_remains_r(tmp_path: Path, pair) -> None:
    versions = _versions("aumc", "aumc", *pair)
    stay_ids = StayIdComparison(
        "omop:visit_occurrence.visit_occurrence_id",
        "aumcdb:admissions.admissionid",
        crosswalk=load_stay_crosswalk(
            pl.DataFrame({"reference_stay_id": [1, 2], "weavehr_stay_id": [1, 2]})
        ),
    )
    comparison = _compare(tmp_path, versions, stay_ids=stay_ids)
    assert set(comparison.coverage["concept"]) == {"hr", "map"}

    review = _review(tmp_path, versions, dataset="aumc", source="aumc")
    table = build_dataset_concept_validation(review, comparison)
    assert _status(table) == {"hr": "R", "map": "R", "resp": "R", "glu": None}
    assert set(table["dataset"]) == {"aumc"}


def test_concept_without_values_on_one_side_is_not_r_plus(tmp_path: Path) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    comparison = _compare(tmp_path, versions)
    evidence = ComparisonEvidence(
        provenance=comparison.provenance,
        coverage=comparison.coverage.with_columns(
            pl.when(pl.col("concept") == "map")
            .then(0)
            .otherwise("weavehr_non_null")
            .alias("weavehr_non_null")
        ),
    )
    table = build_dataset_concept_validation(_review(tmp_path, versions), evidence)
    assert _status(table)["map"] == "R"
    assert _by_concept(table)["map"]["coverage_compared"] is False


def test_conflicting_versions_are_rejected(tmp_path: Path) -> None:
    review = _review(tmp_path, _versions("mimic-iv", "miiv", *SAME))
    comparison = _compare(tmp_path, _versions("mimic-iv", "miiv", *CROSS))
    with pytest.raises(ValueError, match="different WeavEHR dataset versions"):
        build_dataset_concept_validation(review, comparison)


@pytest.mark.parametrize("stays", [(1, 2), (7, 8)])  # full_same_version, not_comparable
def test_persisted_reports_give_the_same_table(tmp_path: Path, stays) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    review = _review(tmp_path, versions)
    reports = tmp_path / "reports"
    comparison = _compare(tmp_path, versions, weavehr_stays=stays, reports_dir=reports)
    _, summary_path = write_item_review(review, tmp_path / "item_review")

    in_memory = build_dataset_concept_validation(review, comparison)
    persisted = build_dataset_concept_validation(
        pl.read_csv(summary_path, infer_schema=False), read_comparison_evidence(reports)
    )
    assert persisted.equals(in_memory)


def test_writer_persists_csv_and_parquet(tmp_path: Path) -> None:
    versions = _versions("mimic-iv", "miiv", *SAME)
    table = build_dataset_concept_validation(
        _review(tmp_path, versions), _compare(tmp_path, versions)
    )
    csv_path, parquet_path = write_dataset_concept_validation(
        table, tmp_path / "out", formats=("csv", "parquet")
    )
    assert csv_path.name == "dataset_concept_validation.csv"
    assert pl.read_parquet(parquet_path).equals(table)
    assert pl.read_csv(csv_path, infer_schema=False)["ricu_status"].to_list() == [
        "R+",
        "R+",
        "R",
        None,
    ]
    with pytest.raises(ValueError, match="Unsupported"):
        write_dataset_concept_validation(table, tmp_path / "out", formats=("xlsx",))
