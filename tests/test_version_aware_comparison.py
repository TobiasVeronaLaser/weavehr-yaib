"""Version-aware WeavEHR <-> RICU comparison scope and reporting."""

import json
from pathlib import Path

import polars as pl
import pytest

from weavehr_yaib.compare import per_stay_reproduction_report, reproduction_accuracy_summary
from weavehr_yaib.stay_ids import (
    RICU_STAY_ID_SPACES,
    StayIdComparison,
    load_stay_crosswalk,
    weavehr_stay_id_space,
)
from weavehr_yaib.versions import (
    DatasetVersion,
    StaleProvenanceError,
    VersionComparison,
    write_weavehr_provenance,
)
from weavehr_yaib.workflow import (
    compare_weavehr_wide_to_ricu,
    compare_weavehr_wide_to_ricu_for_dataset,
    display_comparison_overview,
    normalize_ricu_dynamic_reference,
    normalize_wide_dtypes_for_comparison,
    read_ricu_stay_windows,
    resolve_comparison_versions,
)

VARS = ["hr", "map", "temp", "resp"]
MIIV_STAY_SPACE = "mimic-iv:icustays.stay_id"
MIIV_STAYS = StayIdComparison(MIIV_STAY_SPACE, MIIV_STAY_SPACE)


def _wide(stays: list[int], **extra: list[float]) -> pl.DataFrame:
    n = len(stays) * 3
    return pl.DataFrame(
        {
            "stay_id": [s for s in stays for _ in range(3)],
            "time": [t for _ in stays for t in range(3)],
            "hr": [80.0 + t for _ in stays for t in range(3)],
            "map": [70.0] * n,
            **{k: v * n for k, v in extra.items()},
        }
    )


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    """WeavEHR has stay 4 and concept ``temp`` extra; RICU has stay 3 and ``resp``."""
    weavehr = _wide([1, 2, 4], temp=[37.0])
    # One genuine value difference on a shared key.
    weavehr = weavehr.with_columns(
        pl.when((pl.col("stay_id") == 2) & (pl.col("time") == 1))
        .then(99.0)
        .otherwise(pl.col("hr"))
        .alias("hr")
    )
    reference = _wide([1, 2, 3], resp=[16.0])
    windows = pl.DataFrame({"stay_id": [1, 2, 3], "start": [0.0] * 3, "end": [2.0] * 3})
    paths = {
        "wide": tmp_path / "weavehr_dyn_168h.parquet",
        "reference": tmp_path / "ricu_dynamic_vars_miiv.parquet",
        "windows": tmp_path / "ricu_stay_windows_miiv.parquet",
    }
    weavehr.write_parquet(paths["wide"])
    reference.write_parquet(paths["reference"])
    windows.write_parquet(paths["windows"])
    return paths


def _compare(
    files: dict[str, Path],
    versions: VersionComparison | None,
    stay_ids: StayIdComparison | None = MIIV_STAYS,
    **kwargs,
):
    return compare_weavehr_wide_to_ricu(
        weavehr_wide_path=files["wide"],
        ricu_dynamic_path=files["reference"],
        ricu_stay_windows_path=files["windows"],
        dynamic_vars=VARS,
        versions=versions,
        stay_ids=stay_ids,
        **kwargs,
    )


def _versions(weavehr: tuple, reference: tuple) -> VersionComparison:
    return VersionComparison(
        weavehr=DatasetVersion("mimic-iv", *weavehr),
        reference=DatasetVersion("ricu:miiv", *reference),
    )


def _row(df: pl.DataFrame) -> dict:
    assert df.height == 1
    return df.row(0, named=True)


def test_same_verified_version_keeps_full_comparison(files: dict[str, Path]) -> None:
    result = _compare(files, _versions(("2.2", "extraction_dirs"), ("2.2", "provenance_file")))

    provenance = _row(result.provenance)
    assert provenance["same_version"] is True
    assert provenance["comparison_scope"] == "full"
    assert provenance["validation_level"] == "full_same_version"
    assert provenance["stay_comparison_confidence"] == "high"
    assert provenance["stay_id_version_assumption"] == "same_verified_version"

    # Same numbers as the comparison before version awareness: all RICU-window
    # stays (including RICU-only stay 3) and all requested variables.
    windows = read_ricu_stay_windows(files["windows"])
    weavehr = normalize_wide_dtypes_for_comparison(
        pl.read_parquet(files["wide"]), dynamic_vars=VARS
    )
    reference = normalize_wide_dtypes_for_comparison(
        normalize_ricu_dynamic_reference(
            reference_dynamic_path=files["reference"],
            ricu_windows=windows,
            weavehr_columns=weavehr.columns,
        ),
        columns=weavehr.columns,
        dynamic_vars=VARS,
    )
    stays = windows.select("stay_id")
    expected = reproduction_accuracy_summary(
        per_stay_reproduction_report(
            weavehr.join(stays, on="stay_id", how="semi").lazy(),
            reference.join(stays, on="stay_id", how="semi").lazy(),
            VARS,
        )
    )
    accuracy = result.reproduction_accuracy
    assert accuracy.select(expected.columns).equals(expected)
    assert _row(accuracy)["n_stays_reference"] == 3


def test_cross_version_scores_only_the_shared_scope(files: dict[str, Path]) -> None:
    result = _compare(files, _versions(("3.1", "explicit"), ("2.2", "provenance_file")))

    provenance = _row(result.provenance)
    assert provenance["same_version"] is False
    assert provenance["versions_verified"] is True
    assert provenance["comparison_scope"] == "shared_subset"
    assert provenance["validation_level"] == "shared_subset_cross_version"
    assert provenance["stay_relationship"] == "partial_overlap"

    differences = set(result.scope_differences.iter_rows())
    assert differences == {
        ("stay", "4", "weavehr_only"),
        ("stay", "3", "reference_only"),
        ("concept", "temp", "weavehr_only"),
        ("concept", "resp", "reference_only"),
    }
    overlap = {r["dimension"]: r for r in result.scope_overlap.iter_rows(named=True)}
    assert (overlap["stays"]["n_shared"], overlap["concepts"]["n_shared"]) == (2, 2)

    # Version-specific stays and concepts are not scored as errors.
    assert set(result.per_stay_reproduction["stay_id"]) == {1, 2}
    assert set(result.coverage["concept"]) == {"hr", "map"}
    accuracy = _row(result.reproduction_accuracy)
    assert accuracy["n_stays_reference"] == 2
    assert accuracy["n_stays_only_reference"] == 0
    assert accuracy["n_rows_value_mismatch"] == 1
    # ...but the aggregate carries its scope and provenance.
    assert accuracy["comparison_scope"] == "shared_subset"
    assert accuracy["validation_level"] == "shared_subset_cross_version"
    assert accuracy["weavehr_dataset_version"] == "3.1"
    assert accuracy["reference_dataset_version"] == "2.2"
    assert accuracy["n_scope_weavehr_only_stays"] == 1
    assert accuracy["n_scope_reference_only_concepts"] == 1


def test_assumed_reference_version_is_unverified_even_if_equal(files: dict[str, Path]) -> None:
    result = _compare(files, _versions(("2.2", "explicit"), ("2.2", "ricu_config")))
    provenance = _row(result.provenance)
    assert provenance["same_version"] is True
    assert provenance["reference_version_verified"] is False
    assert provenance["validation_level"] == "shared_subset_unverified_version"
    # Equal but assumed versions do not verify stay ID stability.
    assert provenance["stay_comparison_confidence"] == "medium"
    assert provenance["stay_id_version_assumption"] == "unverified_cross_version_stability"
    assert provenance["comparison_scope"] == "shared_subset"


def test_unknown_version_gives_null_same_version(files: dict[str, Path]) -> None:
    result = _compare(files, None)
    provenance = _row(result.provenance)
    assert provenance["same_version"] is None
    assert provenance["validation_level"] == "shared_subset_unverified_version"
    assert _row(result.reproduction_accuracy)["same_version"] is None


def test_disjoint_stays_are_not_comparable(tmp_path: Path, files: dict[str, Path]) -> None:
    _wide([7, 8]).write_parquet(files["wide"])
    result = _compare(
        files,
        _versions(("2.2", "explicit"), ("2.2", "provenance_file")),
        reports_dir=tmp_path / "reports",
    )
    assert _row(result.provenance)["validation_level"] == "not_comparable"
    assert result.per_stay_reproduction.is_empty()
    assert _row(result.reproduction_accuracy)["validation_level"] == "not_comparable"
    assert set(display_comparison_overview(result)) == {
        "provenance",
        "scope_overlap",
        "reproduction_accuracy",
    }
    assert (tmp_path / "reports" / "provenance.csv").is_file()


def test_for_dataset_resolves_versions_and_scopes_reports_dir(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    write_weavehr_provenance(
        files["wide"],
        DatasetVersion("mimic-iv", "3.1", "extraction_dirs"),
        max_hours=168,
        stay_id_space=MIIV_STAY_SPACE,
    )
    files["reference"].with_suffix(".provenance.json").write_text(
        json.dumps({"source_version_from_url": "2.2", "source_version_declared": "2.2"})
    )

    result = compare_weavehr_wide_to_ricu_for_dataset(
        dataset="mimic-iv",
        output_root=tmp_path,
        concept_root=tmp_path / "concept",
        ricu_concept_dict=tmp_path / "concept-dict.json",
        dynamic_vars=VARS,
    )

    provenance = _row(result.provenance)
    assert provenance["weavehr_version_source"] == "extraction_dirs"
    assert provenance["reference_version_source"] == "provenance_file"
    assert provenance["validation_level"] == "shared_subset_cross_version"
    assert provenance["stay_comparison_basis"] == "direct_identifier_match"
    # MIMIC-IV 3.1 vs 2.2: stay ID stability across versions is not verified.
    assert provenance["stay_comparison_confidence"] == "medium"
    assert provenance["stay_id_version_assumption"] == "unverified_cross_version_stability"
    assert result.reports_dir == tmp_path / "reports/168h/weavehr-3.1__ricu-miiv-2.2"
    assert (result.reports_dir / "scope_differences.csv").is_file()

    with pytest.raises(ValueError, match="rebuild"):
        resolve_comparison_versions(
            dataset="mimic-iv",
            weavehr_wide_path=files["wide"],
            ricu_dynamic_path=files["reference"],
            dataset_version="2.2",
        )


# ---------------------------------------------------------------------------
# Stay identifier spaces
# ---------------------------------------------------------------------------

VERIFIED_SAME = (("1.0", "explicit"), ("1.0", "explicit"))


def test_equal_numbers_in_different_stay_id_spaces_are_not_matched(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    """AUMC: WeavEHR OMOP visit_occurrence_id 1, 2 vs RICU admissionid 1, 2, 3."""
    stay_ids = StayIdComparison(
        "omop:visit_occurrence.visit_occurrence_id", "aumcdb:admissions.admissionid"
    )
    result = _compare(
        files, _versions(*VERIFIED_SAME), stay_ids=stay_ids, reports_dir=tmp_path / "r"
    )

    provenance = _row(result.provenance)
    assert provenance["stay_comparison_basis"] == "side_by_side_only"
    assert provenance["stay_comparison_confidence"] == "not_comparable"
    assert provenance["stay_id_version_assumption"] == "not_applicable"
    assert provenance["stay_relationship"] == "not_directly_comparable"
    assert provenance["validation_level"] == "not_comparable"
    assert provenance["n_scope_shared_stays"] is None
    # Versions and concepts are still reported.
    assert provenance["same_version"] is True
    assert provenance["concept_relationship"] == "partial_overlap"

    # No stay-keyed report is derived from the coincidentally equal numbers.
    for table in (
        result.per_stay_reproduction,
        result.value_diff,
        result.coverage,
        result.window_summary,
        result.window_differences,
    ):
        assert table.is_empty()
    stays = {r["dimension"]: r for r in result.scope_overlap.iter_rows(named=True)}["stays"]
    assert (stays["n_weavehr"], stays["n_reference"], stays["n_shared"]) == (3, 3, None)
    assert stays["relationship"] == "not_directly_comparable"

    # Both stay ID sets are listed separately, including the equal numbers.
    listed = set(result.scope_differences.filter(pl.col("dimension") == "stay").iter_rows())
    assert ("stay", "1", "weavehr") in listed and ("stay", "1", "reference") in listed
    assert ("stay", "4", "weavehr") in listed and ("stay", "3", "reference") in listed
    assert (tmp_path / "r" / "provenance.csv").is_file()


def test_unknown_stay_id_spaces_are_not_matched(files: dict[str, Path]) -> None:
    result = _compare(files, _versions(*VERIFIED_SAME), stay_ids=None)
    provenance = _row(result.provenance)
    assert provenance["weavehr_stay_id_space"] is None
    assert provenance["stay_comparison_basis"] == "side_by_side_only"
    assert provenance["validation_level"] == "not_comparable"


def test_stay_crosswalk_translates_reference_stays(files: dict[str, Path]) -> None:
    # RICU stays 1, 2 correspond to WeavEHR stays 2, 1; RICU stay 3 has no entry.
    crosswalk = pl.DataFrame({"reference_stay_id": [1, 2], "weavehr_stay_id": [2, 1]})
    stay_ids = StayIdComparison(
        "omop:visit_occurrence.visit_occurrence_id",
        "aumcdb:admissions.admissionid",
        crosswalk=load_stay_crosswalk(crosswalk),
    )
    result = _compare(files, _versions(*VERIFIED_SAME), stay_ids=stay_ids)

    provenance = _row(result.provenance)
    assert provenance["stay_comparison_basis"] == "crosswalk"
    assert provenance["stay_comparison_confidence"] == "medium"
    assert provenance["stay_id_version_assumption"] == "crosswalk"
    # Same verified version, but a crosswalk only links the stays it covers:
    # never full validation, metrics only on the mapped stays.
    assert provenance["validation_level"] == "shared_subset_stay_crosswalk"
    assert provenance["comparison_scope"] == "shared_subset"
    assert _row(result.reproduction_accuracy)["n_stays_reference"] == 2
    assert provenance["n_scope_shared_stays"] == 2
    assert provenance["n_scope_reference_stays_without_crosswalk"] == 1
    assert ("stay", "3", "reference_without_crosswalk") in set(result.scope_differences.iter_rows())
    assert set(result.per_stay_reproduction["stay_id"]) == {1, 2}
    # The planted value difference sits in WeavEHR stay 2 = RICU stay 1, which
    # has the same values as RICU stay 2: hr differs at time 1 only.
    assert _row(result.reproduction_accuracy)["n_rows_value_mismatch"] == 1


def test_stay_crosswalk_must_be_one_to_one() -> None:
    with pytest.raises(ValueError, match="one-to-one"):
        load_stay_crosswalk(pl.DataFrame({"reference_stay_id": [1, 2], "weavehr_stay_id": [5, 5]}))


def test_declared_stay_id_spaces() -> None:
    assert weavehr_stay_id_space("aumc", "weavehr_visit_events") != RICU_STAY_ID_SPACES["aumc"]
    # AUMC events carry OMOP visit IDs, so a native admissions table is not trusted.
    assert weavehr_stay_id_space("aumc", "raw_stay_table") is None
    # SIC raw cases use CaseID; WeavEHR SIC subject_id is PatientID.
    assert weavehr_stay_id_space("sic", "raw_stay_table") is None
    assert weavehr_stay_id_space("hirid", "raw_stay_table") == RICU_STAY_ID_SPACES["hirid"]
    assert weavehr_stay_id_space("mimic-iv", "raw_stay_table") == RICU_STAY_ID_SPACES["miiv"]
    assert weavehr_stay_id_space("mimic-iii", "raw_stay_table") != RICU_STAY_ID_SPACES["miiv"]
    assert weavehr_stay_id_space("hirid", "weavehr_hirid_events") == RICU_STAY_ID_SPACES["hirid"]
    assert weavehr_stay_id_space("mimic-iv", "unknown") is None


def test_low_level_compare_reads_ricu_provenance_without_provenance_id(
    files: dict[str, Path],
) -> None:
    """The R export's sidecar has no WeavEHR provenance_id and must still be read."""
    files["reference"].with_suffix(".provenance.json").write_text(
        json.dumps(
            {
                "reference": "ricu",
                "ricu_source": "miiv",
                "ricu_package_version": "0.6.3",
                "source_url": "https://physionet.org/files/mimiciv/2.2",
                "source_version_from_url": "2.2",
                "source_version_declared": None,
            }
        )
    )

    result = compare_weavehr_wide_to_ricu(
        weavehr_wide_path=files["wide"],
        ricu_dynamic_path=files["reference"],
        ricu_stay_windows_path=files["windows"],
        dynamic_vars=VARS,
    )

    # ricu_source "miiv" was read from the sidecar and mapped to RICU's stay space.
    assert _row(result.provenance)["reference_stay_id_space"] == MIIV_STAY_SPACE


def test_low_level_compare_still_rejects_unlinked_weavehr_provenance(
    files: dict[str, Path],
) -> None:
    """WeavEHR sidecars keep requiring the provenance_id stored in the parquet."""
    files["wide"].with_suffix(".provenance.json").write_text(
        json.dumps({"stay_id_space": MIIV_STAY_SPACE})
    )
    with pytest.raises(StaleProvenanceError):
        compare_weavehr_wide_to_ricu(
            weavehr_wide_path=files["wide"],
            ricu_dynamic_path=files["reference"],
            ricu_stay_windows_path=files["windows"],
            dynamic_vars=VARS,
        )
