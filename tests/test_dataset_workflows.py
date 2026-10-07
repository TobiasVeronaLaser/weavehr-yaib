from pathlib import Path

import pytest

from weavehr_yaib.workflow import dataset_ricu_code, default_dataset_paths


@pytest.mark.parametrize(
    ("dataset", "expected"),
    [
        ("mimic-iv", "miiv"),
        ("mimic-iii", "mimic"),
        ("eicu", "eicu"),
        ("hirid", "hirid"),
        ("aumc", "aumc"),
        ("mimic_demo", "mimic_demo"),
        ("eicu_demo", "eicu_demo"),
        ("sicdb", "sic"),
    ],
)
def test_dataset_ricu_code(dataset: str, expected: str) -> None:
    assert dataset_ricu_code(dataset) == expected


def test_nwicu_is_not_a_native_ricu_dataset() -> None:
    with pytest.raises(ValueError, match="Unsupported dataset"):
        dataset_ricu_code("nwicu")


def test_explicit_stay_file_is_used_for_non_miiv_dataset(tmp_path: Path) -> None:
    stay_file = tmp_path / "patient.csv.gz"

    paths = default_dataset_paths(
        dataset="eicu",
        output_root=tmp_path,
        concept_root=tmp_path / "concept",
        icustays_csv=stay_file,
        ricu_concept_dict=tmp_path / "concept-dict.json",
    )

    assert paths.icustays_csv == stay_file.resolve()
