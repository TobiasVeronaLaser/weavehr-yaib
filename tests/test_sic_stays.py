"""SIC stays from WeavEHR cases events: one stay per CaseID on WeavEHR's time axis."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from weavehr_yaib import (
    build_and_write_yaib_wide_for_dataset,
    compare_weavehr_wide_to_ricu_for_dataset,
    weavehr_sic_stays,
    write_all_concepts_wide,
)
from weavehr_yaib.stays import dataset_stay_spec
from weavehr_yaib.transform import build_dynamic_table
from weavehr_yaib.versions import read_provenance_field

# WeavEHR SIC axis: Jan 1 of the patient's first admission year
# + OffsetAfterFirstAdmission + Offset (seconds).
YEAR_BASE = datetime(2013, 1, 1)

# (PatientID, CaseID, OffsetAfterFirstAdmission, last observation hour).
# Patient 7's first case is CaseID 7 and its second case is CaseID 8, while
# patient 8 has case 20: equal PatientID/CaseID numbers must not collapse stays.
CASES = [(7, 7, timedelta(0), 5), (7, 8, timedelta(days=10), 200), (8, 20, timedelta(0), 3)]

# (PatientID, CaseID, hours after the case's admission, heart rate)
HR_EVENTS = [
    (7, 7, 0.5, 80.0),  # case 7, stay hour 0
    (7, 7, 2.17, 82.0),  # case 7, stay hour 2
    (7, 8, 1.0, 90.0),  # case 8, stay hour 1 (ten days later on the patient axis)
    (7, 8, 170.0, 99.0),  # case 8, beyond the 168-hour cutoff
    (8, 20, 1.0, 70.0),  # patient 8, case 20
]


def _admission(case_id: int) -> datetime:
    return next(YEAR_BASE + off for _, c, off, _ in CASES if c == case_id)


def _write(path: Path, df: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def _events(rows: list[tuple[int, int, datetime]], **extra) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "subject_id": pl.Series([r[0] for r in rows], dtype=pl.Int64),
            "time": pl.Series([r[2] for r in rows], dtype=pl.Datetime("us")),
            **extra,
        }
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """WeavEHR SIC project with extraction events and a heart-rate concept."""
    root = tmp_path / "project"
    for sub in ("datasets", "configs"):
        (root / sub).mkdir(parents=True)
    extraction = root / "workspace/extraction/sic/1.0.6"
    # Extraction keeps the native CaseID dtype for the case_id extension.
    _write(
        extraction / "cases/ICU_ADMISSION.parquet",
        _events(
            [(p, c, YEAR_BASE + off) for p, c, off, _ in CASES],
            case_id=[c for _, c, _, _ in CASES],
        ),
    )
    _write(
        extraction / "data_float_h/OBSERVATION.parquet",
        _events(
            [(p, c, YEAR_BASE + off + timedelta(hours=end)) for p, c, off, end in CASES],
            case_id=[c for _, c, _, _ in CASES],
        ),
    )
    # Concept outputs write extension columns as strings.
    _write(
        root / "workspace/concept/heart_rate/1.0.0/sic.parquet",
        _events(
            [(p, c, _admission(c) + timedelta(hours=h)) for p, c, h, _ in HR_EVENTS],
            numeric_value=pl.Series([v for *_, v in HR_EVENTS], dtype=pl.Float32),
            case_id=[str(c) for _, c, _, _ in HR_EVENTS],
        ),
    )
    return root


def _concept_dict(tmp_path: Path) -> Path:
    path = tmp_path / "concept-dict.json"
    path.write_text("{}")
    return path


def _export(project: Path, tmp_path: Path):
    return build_and_write_yaib_wide_for_dataset(
        dataset="sic",
        max_hours=168,
        output_root=tmp_path / "out",
        concept_root=project / "workspace/concept",
        ricu_concept_dict=_concept_dict(tmp_path),
        dynamic_vars=["hr"],
    )


def _values(path: Path, column: str) -> set[tuple[int, int, float]]:
    df = pl.read_parquet(path).filter(pl.col(column).is_not_null())
    return set(df.select("stay_id", "time", column).iter_rows())


EXPECTED_HR = {(7, 0, 80.0), (7, 2, 82.0), (8, 1, 90.0), (20, 1, 70.0)}


def test_sic_stays_are_cases_on_the_weavehr_axis(project: Path) -> None:
    stays = weavehr_sic_stays(project / "workspace").sort("stay_id").collect()
    assert stays["stay_id"].to_list() == [7, 8, 20]
    # Patient identity is kept: both cases of patient 7 stay separate.
    assert stays["subject_id"].to_list() == [7, 7, 8]
    assert (stays["outtime_hours"] - stays["intime_hours"]).to_list() == [5.0, 200.0, 3.0]
    case_8_start = (_admission(8) - datetime(1970, 1, 1)).total_seconds() / 3600
    assert stays.filter(pl.col("stay_id") == 8)["intime_hours"].item() == case_8_start


def test_sic_wide_assigns_events_to_their_case(project: Path, tmp_path: Path) -> None:
    result = _export(project, tmp_path)
    wide = pl.read_parquet(result.output_path)

    # Hour bins are relative to each case; the hour-170 event is cut at 168.
    assert _values(result.output_path, "hr") == EXPECTED_HR
    times = {s: wide.filter(pl.col("stay_id") == s)["time"].to_list() for s in (7, 8, 20)}
    assert times[7] == list(range(6))
    assert times[8] == list(range(169))
    assert times[20] == list(range(4))

    assert read_provenance_field(result.output_path, "stay_source") == "weavehr_sic_cases_events"
    assert read_provenance_field(result.output_path, "stay_id_space") == "sicdb:cases.caseid"


def test_sic_all_concepts_assigns_events_to_their_case(project: Path) -> None:
    result = write_all_concepts_wide(dataset="sic", weavehr_output=project, max_hours=168)
    assert _values(result.output_path, "heart_rate") == EXPECTED_HR


def test_sic_requires_case_id_on_concept_events(project: Path, tmp_path: Path) -> None:
    path = project / "workspace/concept/heart_rate/1.0.0/sic.parquet"
    pl.read_parquet(path).drop("case_id").write_parquet(path)
    with pytest.raises(ValueError, match='case_id: col\\("case_id"\\)'):
        _export(project, tmp_path)


def test_sic_patient_id_is_never_used_as_stay_id(project: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PatientID, not an ICU stay ID"):
        build_dynamic_table(
            concept_root=project / "workspace/concept",
            stay_spec=dataset_stay_spec("sic"),
            dataset="sic",
            dynamic_vars=["hr"],
            include_grid=False,
            ricu_concept_dict=_concept_dict(tmp_path),
        )


def test_sic_compares_directly_with_ricu_case_ids(project: Path, tmp_path: Path) -> None:
    result = _export(project, tmp_path)
    out = tmp_path / "out"
    # RICU reference keyed by CaseID with the same values.
    pl.DataFrame(
        {
            "CaseID": [7, 7, 8, 20],
            "time": [0, 2, 1, 1],
            "hr": [80.0, 82.0, 90.0, 70.0],
        }
    ).write_parquet(out / "ricu_dynamic_vars_sic.parquet")
    pl.DataFrame(
        {"CaseID": [7, 8, 20], "start": [0.0, 0.0, 0.0], "end": [5.0, 200.0, 3.0]}
    ).write_parquet(out / "ricu_stay_windows_sic.parquet")
    (out / "ricu_dynamic_vars_sic.provenance.json").write_text(
        json.dumps({"ricu_source": "sic", "source_version_declared": "1.0.6"})
    )

    comparison = compare_weavehr_wide_to_ricu_for_dataset(
        dataset="sic",
        output_root=out,
        concept_root=project / "workspace/concept",
        ricu_concept_dict=_concept_dict(tmp_path),
        weavehr_wide_path=result.output_path,
        dynamic_vars=["hr"],
    )

    provenance = comparison.provenance.row(0, named=True)
    assert provenance["weavehr_stay_id_space"] == "sicdb:cases.caseid"
    assert provenance["reference_stay_id_space"] == "sicdb:cases.caseid"
    assert provenance["stay_comparison_basis"] == "direct_identifier_match"
    assert provenance["stay_relationship"] == "equal"
    assert provenance["validation_level"] == "full_same_version"
    accuracy = comparison.reproduction_accuracy.row(0, named=True)
    assert accuracy["n_stays_common"] == 3
    assert accuracy["n_rows_value_mismatch"] == 0
