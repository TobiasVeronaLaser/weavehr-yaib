import datetime as dt

import polars as pl

from openicu_yaib.transform import (
    map_events_to_stays,
    map_subject_events_to_dataset_stays,
)


def test_dataset_relative_hours_use_floor_bins() -> None:
    events = pl.DataFrame(
        {
            "subject_id": [1] * 8,
            "time_hours": [10.00, 10.49, 10.50, 10.99, 11.00, 11.49, 11.99, 12.00],
            "numeric_value": [1.0] * 8,
        }
    ).lazy()

    stays = pl.DataFrame(
        {
            "subject_id": [1],
            "stay_id": [100],
            "intime_hours": [10.0],
            "outtime_hours": [20.0],
        }
    ).lazy()

    result = (
        map_subject_events_to_dataset_stays(events, stays)
        .select("time")
        .collect()
        .get_column("time")
        .to_list()
    )

    assert result == [0, 0, 0, 0, 1, 1, 1, 2]


def test_datetime_relative_hours_use_floor_bins() -> None:
    intime = dt.datetime(2026, 1, 1, 0, 0)

    offsets_minutes = [0, 29, 30, 59, 60, 89, 119, 120]

    events = pl.DataFrame(
        {
            "subject_id": [1] * len(offsets_minutes),
            "time": [intime + dt.timedelta(minutes=x) for x in offsets_minutes],
            "numeric_value": [1.0] * len(offsets_minutes),
        }
    ).lazy()

    stays = pl.DataFrame(
        {
            "subject_id": [1],
            "stay_id": [100],
            "intime": [intime],
            "outtime": [intime + dt.timedelta(hours=10)],
        }
    ).lazy()

    result = (
        map_events_to_stays(events, stays).select("time").collect().get_column("time").to_list()
    )

    assert result == [0, 0, 0, 0, 1, 1, 1, 2]


def test_dataset_stay_mapping_prefers_visit_occurrence_id() -> None:
    events = pl.DataFrame(
        {
            "subject_id": [1, 1],
            "visit_occurrence_id": [100, 200],
            "time_hours": [5.0, 5.0],
            "numeric_value": [10.0, 20.0],
        }
    ).lazy()

    stays = pl.DataFrame(
        {
            "subject_id": [1, 1],
            "stay_id": [100, 200],
            "intime_hours": [0.0, 0.0],
            "outtime_hours": [10.0, 10.0],
        }
    ).lazy()

    result = (
        map_subject_events_to_dataset_stays(events, stays)
        .sort("stay_id")
        .collect()
    )

    assert result["stay_id"].to_list() == [100, 200]
    assert result["numeric_value"].to_list() == [10.0, 20.0]
