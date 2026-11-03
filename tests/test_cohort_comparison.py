from pathlib import Path

import polars as pl

from weavehr_yaib.cohort_comparison import compare_outputs, compare_task


def write_task(task_dir: Path, outc: dict, dyn: dict, sta: dict, attrition: list[tuple]) -> None:
    task_dir.mkdir(parents=True)
    pl.DataFrame(outc).write_parquet(task_dir / "outc.parquet")
    pl.DataFrame(dyn).write_parquet(task_dir / "dyn.parquet")
    pl.DataFrame(sta).write_parquet(task_dir / "sta.parquet")
    pl.DataFrame(
        [(i, *row) for i, row in enumerate(attrition)],
        schema=["", "desc", "n_input", "n_criterion", "n_excluded", "n_left"],
        orient="row",
    ).write_csv(task_dir / "attrition.csv")


def test_compare_binary_task(tmp_path: Path) -> None:
    write_task(
        tmp_path / "ricu" / "mortality24" / "miiv",
        outc={"stay_id": [1, 2, 3], "label": [0, 1, 0]},
        dyn={"stay_id": [1, 1, 2, 3], "time": [0.0, 1.0, 0.0, 0.0], "hr": [80.0, 81.0, 90.0, None]},
        sta={"stay_id": [1, 2, 3], "age": [60.0, 70.0, 80.0], "sex": ["Male", "Female", "Male"]},
        attrition=[("Aged < 18 years", 4, 1, 1, 3)],
    )
    write_task(
        tmp_path / "weavehr" / "mortality24" / "mimic-iv",
        outc={"stay_id": [1, 2], "label": [0, 1]},
        dyn={"stay_id": [1, 1, 2], "time": [0, 1, 0], "hr": [80.0, 85.0, 90.0]},
        sta={"stay_id": [1, 2], "age": [60.0, 70.0], "sex": ["Male", "Male"]},
        attrition=[("Aged < 18 years", 4, 2, 2, 2)],
    )

    res = compare_task(
        tmp_path / "ricu" / "mortality24" / "miiv",
        tmp_path / "weavehr" / "mortality24" / "mimic-iv",
    )

    assert res.cohort.row(0, named=True) == {
        "n_ricu": 3,
        "n_weavehr": 2,
        "n_both": 2,
        "n_only_ricu": 1,
        "n_only_weavehr": 0,
    }
    labels = res.labels.row(0, named=True)
    assert labels["n_common"] == 2 and labels["agreement"] == 1.0
    assert labels["positive_stays_ricu"] == labels["positive_stays_both"] == 1
    variables = {row["variable"]: row for row in res.variables.iter_rows(named=True)}
    assert variables["hr"]["n_both"] == 3 and abs(variables["hr"]["equal"] - 2 / 3) < 1e-9
    assert variables["age"]["equal"] == 1.0 and variables["age"]["coverage"] == 1.0
    assert variables["sex"]["equal"] == 0.5
    assert res.attrition.row(0, named=True) == {
        "desc": "Aged < 18 years",
        "n_excluded_ricu": 1,
        "n_left_ricu": 3,
        "n_excluded_weavehr": 2,
        "n_left_weavehr": 2,
    }


def test_compare_outputs_regression_without_time(tmp_path: Path) -> None:
    for side, src, label in (
        ("ricu", "miiv", [10.0, 9.0, 5.0]),
        ("weavehr", "mimic-iv", [10.0, 9.0, 4.0]),
    ):
        write_task(
            tmp_path / side / "los" / src,
            outc={"stay_id": [1, 1, 2], "label": label},
            dyn={"stay_id": [1, 1, 2], "time": [0, 1, 0], "hr": [80.0, 81.0, 90.0]},
            sta={"stay_id": [1, 2], "age": [60.0, 70.0]},
            attrition=[("Invalid length of stay", 2, 0, 0, 2)],
        )

    summary = compare_outputs(
        tmp_path / "ricu", tmp_path / "weavehr", "miiv", "mimic-iv", tmp_path / "reports"
    )

    row = summary.row(0, named=True)
    assert row["task"] == "los" and row["n_both"] == 2
    assert abs(row["label_agreement"] - 2 / 3) < 1e-9
    assert row["variables_differing"] == ""
    labels = pl.read_csv(tmp_path / "reports" / "los" / "labels.csv")
    assert labels["keys"][0] == "stay_id/row" and labels["n_common"][0] == 3
    assert (tmp_path / "reports" / "summary.csv").exists()
