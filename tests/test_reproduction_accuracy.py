import math

import polars as pl

from weavehr_yaib.compare import (
    per_stay_reproduction_report,
    reproduction_accuracy_summary,
)


def test_per_stay_reproduction_and_summary() -> None:
    weavehr = pl.DataFrame(
        {
            "stay_id": [1, 1, 2, 2, 4],
            "time": [0, 1, 0, 1, 0],
            "hr": [80.0, None, 70.0, 71.0, 90.0],
        }
    ).lazy()
    reference = pl.DataFrame(
        {
            "stay_id": [1, 1, 2, 2, 3],
            "time": [0, 1, 0, 2, 0],
            "hr": [80.0, None, 70.0, 72.0, 60.0],
        }
    ).lazy()

    per_stay = per_stay_reproduction_report(weavehr, reference, ["hr"])

    stay_1 = per_stay.filter(pl.col("stay_id") == 1).row(0, named=True)
    assert stay_1["content_identical"] is True
    assert stay_1["n_equal_rows"] == 2

    stay_2 = per_stay.filter(pl.col("stay_id") == 2).row(0, named=True)
    assert stay_2["content_identical"] is False
    assert stay_2["n_common_rows"] == 1
    assert stay_2["n_only_weavehr_rows"] == 1
    assert stay_2["n_only_reference_rows"] == 1

    summary = reproduction_accuracy_summary(per_stay).row(0, named=True)
    assert summary["n_stays_weavehr"] == 3
    assert summary["n_stays_reference"] == 3
    assert summary["n_stays_common"] == 2
    assert summary["n_common_stays_identical"] == 1
    assert summary["stay_count_error"] == 0.0
    assert summary["total_row_count_error"] == 0.0
    assert math.isclose(summary["common_stay_exact_match_rate"], 0.5)
    assert math.isclose(summary["row_content_disagreement_rate"], 4 / 7)
