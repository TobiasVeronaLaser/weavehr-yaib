from pathlib import Path

import polars as pl
import pytest

from weavehr_yaib.outcome_validation import (
    compare_categorical_outcome,
    write_outcome_comparison,
)


def test_exact_categorical_outcome_match() -> None:
    weavehr = pl.DataFrame(
        {
            "subject_id": [1, 2, 3],
            "status": ["alive", "dead", None],
        }
    )
    reference = pl.DataFrame(
        {
            "subject_id": [1, 2, 3],
            "death": ["alive", "dead", None],
        }
    )

    result = compare_categorical_outcome(
        weavehr,
        reference,
        keys=["subject_id"],
        weavehr_value="status",
        reference_value="death",
    )

    row = result.summary.row(0, named=True)
    assert row == {
        "weavehr_rows": 3,
        "reference_rows": 3,
        "joined_rows": 3,
        "shared_rows": 3,
        "only_weavehr_rows": 0,
        "only_reference_rows": 0,
        "both_non_null": 2,
        "both_null": 1,
        "only_weavehr_value": 0,
        "only_reference_value": 0,
        "equal_non_null": 2,
        "different_non_null": 0,
        "equal_including_null": 3,
    }
    assert result.disagreements.is_empty()


def test_value_and_missingness_disagreements_are_reported() -> None:
    weavehr = pl.DataFrame(
        {
            "subject_id": [1, 2, 3],
            "status": ["alive", "dead", None],
        }
    )
    reference = pl.DataFrame(
        {
            "subject_id": [1, 2, 3],
            "death": ["dead", None, "alive"],
        }
    )

    result = compare_categorical_outcome(
        weavehr,
        reference,
        keys=["subject_id"],
        weavehr_value="status",
        reference_value="death",
    )

    row = result.summary.row(0, named=True)
    assert row["different_non_null"] == 1
    assert row["only_weavehr_value"] == 1
    assert row["only_reference_value"] == 1
    assert result.disagreements.height == 3


def test_missing_rows_are_distinct_from_null_outcomes() -> None:
    weavehr = pl.DataFrame(
        {
            "subject_id": [1, 2],
            "status": [None, "dead"],
        }
    )
    reference = pl.DataFrame(
        {
            "subject_id": [1, 3],
            "death": [None, "alive"],
        }
    )

    result = compare_categorical_outcome(
        weavehr,
        reference,
        keys=["subject_id"],
        weavehr_value="status",
        reference_value="death",
    )

    row = result.summary.row(0, named=True)

    assert row["weavehr_rows"] == 2
    assert row["reference_rows"] == 2
    assert row["joined_rows"] == 3
    assert row["shared_rows"] == 1
    assert row["only_weavehr_rows"] == 1
    assert row["only_reference_rows"] == 1
    assert row["both_null"] == 1
    assert row["only_weavehr_value"] == 0
    assert row["only_reference_value"] == 0
    assert result.disagreements.height == 2


def test_duplicate_keys_are_rejected() -> None:
    weavehr = pl.DataFrame(
        {
            "subject_id": [1, 1],
            "status": ["alive", "alive"],
        }
    )
    reference = pl.DataFrame(
        {
            "subject_id": [1],
            "death": ["alive"],
        }
    )

    with pytest.raises(ValueError, match="duplicated outcome key"):
        compare_categorical_outcome(
            weavehr,
            reference,
            keys=["subject_id"],
            weavehr_value="status",
            reference_value="death",
        )


def test_writer_persists_reports(tmp_path: Path) -> None:
    result = compare_categorical_outcome(
        pl.DataFrame({"id": [1], "status": ["dead"]}),
        pl.DataFrame({"id": [1], "death": ["dead"]}),
        keys=["id"],
        weavehr_value="status",
        reference_value="death",
    )

    summary, disagreements = write_outcome_comparison(result, tmp_path)

    assert pl.read_csv(summary).height == 1
    assert disagreements.is_file()


def test_mimic_mortality_normalization_matches_ricu_definition() -> None:
    from datetime import datetime

    from weavehr_yaib.outcome_validation import (
        normalize_mimic_mortality_reference,
        normalize_mimic_mortality_weavehr,
    )

    times = [
        datetime(2180, 5, 7, 17, 15),
        datetime(2180, 6, 27, 18, 49),
    ]

    weavehr = pl.DataFrame(
        {
            "subject_id": [10000032, 10000032],
            "time": times,
            "numeric_value": [0.0, 1.0],
        }
    )
    reference = pl.DataFrame(
        {
            "subject_id": [10000032, 10000032],
            "dischtime": times,
            "hospital_expire_flag": [0, 1],
        }
    )

    w = normalize_mimic_mortality_weavehr(weavehr)
    r = normalize_mimic_mortality_reference(reference)

    assert w.equals(r)


def test_mimic_reference_normalization_removes_timezone() -> None:
    from datetime import datetime, timezone

    from weavehr_yaib.outcome_validation import normalize_mimic_mortality_reference

    reference = pl.DataFrame(
        {
            "subject_id": [1],
            "dischtime": pl.Series(
                [datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)]
            ),
            "hospital_expire_flag": [1],
        }
    )

    out = normalize_mimic_mortality_reference(reference)

    assert out.schema["dischtime"] == pl.Datetime("us")
    assert out["dischtime"][0] == datetime(2020, 1, 1, 12, 0)


def test_eicu_mortality_collapses_icu_stays_to_hospital_stay() -> None:
    from weavehr_yaib.outcome_validation import (
        normalize_eicu_mortality_reference,
        normalize_eicu_mortality_weavehr,
    )

    reference = pl.DataFrame(
        {
            "patienthealthsystemstayid": [10, 10, 20, 30],
            "hospitaldischargestatus": ["Alive", "Alive", "Expired", None],
        }
    )
    weavehr = pl.DataFrame(
        {
            "subject_id": [10, 20, 30],
            "text_value": ["Alive", "Expired", ""],
        }
    )

    r = normalize_eicu_mortality_reference(reference)
    w = normalize_eicu_mortality_weavehr(weavehr).sort(
        "patienthealthsystemstayid"
    )

    assert r.equals(w)


def test_eicu_conflicting_hospital_status_is_rejected() -> None:
    from weavehr_yaib.outcome_validation import normalize_eicu_mortality_reference

    reference = pl.DataFrame(
        {
            "patienthealthsystemstayid": [10, 10],
            "hospitaldischargestatus": ["Alive", "Expired"],
        }
    )

    with pytest.raises(ValueError, match="conflicting non-null"):
        normalize_eicu_mortality_reference(reference)


def test_hirid_mortality_normalization_preserves_missing_status() -> None:
    from weavehr_yaib.outcome_validation import (
        normalize_hirid_mortality_reference,
        normalize_hirid_mortality_weavehr,
    )

    weavehr = pl.DataFrame(
        {
            "subject_id": [1, 2, 3],
            "text_value": ["alive", "dead", None],
        }
    )
    reference = pl.DataFrame(
        {
            "patientid": [1, 2, 3],
            "discharge_status": ["alive", "dead", None],
        }
    )

    w = normalize_hirid_mortality_weavehr(weavehr)
    r = normalize_hirid_mortality_reference(reference)

    assert w.equals(r)
