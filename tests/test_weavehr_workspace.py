"""WeavEHR project layout: workspace detection, step output lookup, AUMC/HiRID stays."""

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from weavehr_yaib import (
    build_all_concepts_wide,
    build_and_write_yaib_wide,
    build_and_write_yaib_wide_for_dataset,
    concept_root_from_output,
    find_step_output_file,
    resolve_weavehr_workspace,
    weavehr_aumc_stays,
    weavehr_hirid_stays,
    write_all_concepts_wide,
)
from weavehr_yaib.stays import dataset_stay_spec


def _project(tmp_path: Path) -> Path:
    """Create the directories a ``weavehr.WeavEHRProject`` sets up."""
    project = tmp_path / "project"
    for sub in ("datasets", "workspace", "configs"):
        (project / sub).mkdir(parents=True)
    return project


def _write(path: Path, df: pl.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    return path


def _events(subject_ids, times, **columns) -> pl.DataFrame:
    """Build a frame with WeavEHR's MEDS output dtypes."""
    return pl.DataFrame(
        {
            "subject_id": pl.Series(subject_ids, dtype=pl.Int64),
            "time": pl.Series(times, dtype=pl.Datetime("us")),
            **columns,
        }
    )


def test_resolve_workspace_from_weavehr_project_root(tmp_path: Path) -> None:
    project = _project(tmp_path)
    workspace = project / "workspace"

    assert resolve_weavehr_workspace(project) == workspace
    assert resolve_weavehr_workspace(workspace) == workspace
    assert resolve_weavehr_workspace(workspace / "concept") == workspace
    assert concept_root_from_output(project) == workspace / "concept"


def test_resolve_workspace_keeps_arbitrary_directory(tmp_path: Path) -> None:
    # A "workspace" subfolder alone does not make a WeavEHR project.
    (tmp_path / "out" / "workspace").mkdir(parents=True)

    assert resolve_weavehr_workspace(tmp_path / "out") == tmp_path / "out"


def test_find_step_output_prefers_workspace_then_collected_dataset(tmp_path: Path) -> None:
    workspace = _project(tmp_path) / "workspace"
    collected = _write(
        workspace.parent
        / "datasets/extraction/data/aumc/1.5.0/visit_occurrence/VISIT_START.parquet",
        pl.DataFrame({"x": [1]}),
    )
    assert find_step_output_file(workspace, "aumc", "VISIT_START.parquet") == collected

    in_workspace = _write(
        workspace / "extraction/aumc/1.5.0/visit_occurrence/VISIT_START.parquet",
        pl.DataFrame({"x": [1]}),
    )
    assert find_step_output_file(workspace, "aumc", "VISIT_START.parquet") == in_workspace


def test_find_step_output_rejects_missing_and_ambiguous(tmp_path: Path) -> None:
    workspace = _project(tmp_path) / "workspace"
    with pytest.raises(FileNotFoundError, match="any of"):
        find_step_output_file(workspace, "hirid", "OBSERVATION.parquet")

    for version in ("1.0.6", "1.0.8"):
        _write(workspace / f"extraction/sic/{version}/cases/X.parquet", pl.DataFrame({"x": [1]}))
    with pytest.raises(FileNotFoundError, match="exactly one"):
        find_step_output_file(workspace, "sic", "X.parquet")


def test_hirid_stays_from_weavehr_extraction(tmp_path: Path) -> None:
    workspace = _project(tmp_path) / "workspace"
    base = workspace / "extraction/hirid/1.1.1"
    _write(
        base / "general/ICU_ADMISSION.parquet",
        _events([7], [datetime(2020, 1, 1, 0, 0)]),
    )
    _write(
        base / "observations/OBSERVATION.parquet",
        _events([7, 7], [datetime(2020, 1, 1, 2, 0), datetime(2020, 1, 1, 9, 30)]),
    )

    stays = weavehr_hirid_stays(workspace).collect()

    assert stays["stay_id"].to_list() == [7]
    assert stays["outtime_hours"][0] - stays["intime_hours"][0] == pytest.approx(9.5)


def _aumc_project(tmp_path: Path) -> Path:
    """AUMC project: one patient, two ICU admissions, String visit_occurrence_id.

    WeavEHR writes concept extension columns as strings, so the provenance
    column arrives as String and must be cast to Int64 before matching stays.
    """
    project = _project(tmp_path)
    extraction = project / "datasets/extraction/data/aumc/1.5.0/visit_occurrence"
    _write(
        extraction / "VISIT_START.parquet",
        _events(
            [1, 1],
            [datetime(2020, 1, 1, 0, 0), datetime(2020, 1, 2, 0, 0)],
            visit_occurrence_id=pl.Series([10, 11], dtype=pl.Int64),
        ),
    )
    _write(
        extraction / "VISIT_END.parquet",
        _events(
            [1, 1],
            [datetime(2020, 1, 1, 5, 0), datetime(2020, 1, 2, 3, 0)],
            visit_occurrence_id=pl.Series([10, 11], dtype=pl.Int64),
        ),
    )
    _write(
        project / "workspace/concept/heart_rate/1.0.0/aumc.parquet",
        _events(
            [1, 1, 1],
            [
                datetime(2020, 1, 1, 1, 30),
                datetime(2020, 1, 2, 1, 10),
                # Belongs to admission 10 but falls inside admission 11's
                # window: it must be dropped, not reassigned to admission 11.
                datetime(2020, 1, 2, 1, 20),
            ],
            code=["heart_rate//bpm"] * 3,
            numeric_value=pl.Series([80.0, 90.0, 999.0], dtype=pl.Float32),
            text_value=pl.Series([None] * 3, dtype=pl.String),
            visit_occurrence_id=pl.Series(["10", "11", "10"], dtype=pl.String),
        ),
    )
    return project


def _hr_by_key(path: Path, column: str) -> dict[tuple[int, int], float]:
    df = pl.read_parquet(path).filter(pl.col(column).is_not_null())
    return {(s, t): v for s, t, v in df.select("stay_id", "time", column).iter_rows()}


def test_aumc_string_visit_occurrence_id_preserves_provenance_in_yaib_wide(
    tmp_path: Path,
) -> None:
    project = _aumc_project(tmp_path)
    concept_dict = tmp_path / "concept-dict.json"
    concept_dict.write_text(json.dumps({}))

    result = build_and_write_yaib_wide_for_dataset(
        dataset="aumc",
        max_hours=168,
        output_root=tmp_path / "out",
        concept_root=concept_root_from_output(project),
        ricu_concept_dict=concept_dict,
        dynamic_vars=["hr"],
    )

    assert result.output_path.name == "weavehr_dyn_168h.parquet"
    assert _hr_by_key(result.output_path, "hr") == {(10, 1): 80.0, (11, 1): 90.0}
    wide = pl.read_parquet(result.output_path)
    assert wide.filter(pl.col("stay_id") == 10)["time"].to_list() == list(range(6))
    assert wide.filter(pl.col("stay_id") == 11)["time"].to_list() == list(range(4))


def test_aumc_string_visit_occurrence_id_preserves_provenance_in_all_concepts(
    tmp_path: Path,
) -> None:
    project = _aumc_project(tmp_path)

    result = write_all_concepts_wide(dataset="aumc", weavehr_output=project, max_hours=168)

    assert result.output_path == (
        project / "workspace/yaib/aumc/weavehr_all_concepts_wide_168h.parquet"
    )
    assert result.concepts == ("heart_rate",)
    assert _hr_by_key(result.output_path, "heart_rate") == {(10, 1): 80.0, (11, 1): 90.0}


def test_aumc_stays_from_collected_extraction(tmp_path: Path) -> None:
    project = _aumc_project(tmp_path)

    stays = weavehr_aumc_stays(project / "workspace").sort("stay_id").collect()

    assert stays["stay_id"].to_list() == [10, 11]
    assert (stays["outtime_hours"] - stays["intime_hours"]).to_list() == [5.0, 3.0]


# ---------------------------------------------------------------------------
# AUMC: OMOP concept events must not be joined to a native admissions table
# ---------------------------------------------------------------------------


def _native_admissions(tmp_path: Path) -> Path:
    """Native AmsterdamUMCdb admissions whose IDs numerically equal the OMOP IDs.

    patientid 1 / admissionid 10, 11 look like person_id 1 / visit_occurrence_id
    10, 11 of the WeavEHR project, but belong to a different identifier space.
    """
    path = tmp_path / "admissions.csv"
    pl.DataFrame(
        {
            "patientid": [1, 1],
            "admissionid": [10, 11],
            "admittedat": [0, 86_400_000],
            "dischargedat": [18_000_000, 97_200_000],
        }
    ).write_csv(path)
    return path


def test_aumc_raw_admissions_are_not_joined_to_omop_ids_in_yaib_wide(tmp_path: Path) -> None:
    project = _aumc_project(tmp_path)
    concept_dict = tmp_path / "concept-dict.json"
    concept_dict.write_text("{}")

    with pytest.raises(ValueError, match="not joined by equal numbers"):
        build_and_write_yaib_wide_for_dataset(
            dataset="aumc",
            max_hours=168,
            output_root=tmp_path / "out",
            concept_root=concept_root_from_output(project),
            icustays_csv=_native_admissions(tmp_path),
            ricu_concept_dict=concept_dict,
            dynamic_vars=["hr"],
        )


def test_aumc_raw_admissions_are_not_joined_to_omop_ids_in_all_concepts(tmp_path: Path) -> None:
    project = _aumc_project(tmp_path)
    with pytest.raises(ValueError, match="VISIT_START/VISIT_END"):
        write_all_concepts_wide(
            dataset="aumc",
            weavehr_output=project,
            stays_path=_native_admissions(tmp_path),
            max_hours=168,
        )


def test_aumc_discovered_raw_admissions_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _aumc_project(tmp_path)
    monkeypatch.setenv("WEAVEHR_YAIB_AUMC_STAYS", str(_native_admissions(tmp_path)))
    with pytest.raises(ValueError, match="person_id and visit_occurrence_id"):
        build_all_concepts_wide(
            dataset="aumc", concept_root=concept_root_from_output(project), max_hours=168
        )


def test_sic_raw_cases_are_not_joined_to_patient_ids(tmp_path: Path) -> None:
    """WeavEHR SIC subject_id is PatientID 5; the raw cases table has CaseID 5."""
    concept_root = tmp_path / "concept"
    _write(
        concept_root / "heart_rate/1.0.0/sic.parquet",
        _events([5], [datetime(2013, 1, 1, 1)], numeric_value=pl.Series([80.0], dtype=pl.Float32)),
    )
    cases = tmp_path / "cases.csv"
    pl.DataFrame({"CaseID": [5], "ICUOffset": [0], "TimeOfStay": [600]}).write_csv(cases)
    concept_dict = tmp_path / "concept-dict.json"
    concept_dict.write_text("{}")

    with pytest.raises(ValueError, match="PatientID to CaseID"):
        build_all_concepts_wide(dataset="sic", concept_root=concept_root, stays_path=cases)
    with pytest.raises(ValueError, match="PatientID to CaseID"):
        build_and_write_yaib_wide(
            concept_root=concept_root,
            icustays_csv=cases,
            stay_spec=dataset_stay_spec("sic"),
            ricu_concept_dict=concept_dict,
            output_path=tmp_path / "out.parquet",
            dataset="sic",
            dynamic_vars=["hr"],
        )
