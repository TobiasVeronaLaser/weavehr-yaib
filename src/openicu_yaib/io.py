"""Input helpers for OpenICU concept parquets and MIMIC-IV ICU stays."""

from __future__ import annotations

from pathlib import Path

import polars as pl


def find_concept_file(
    concept_root: str | Path,
    openicu_concept: str,
    *,
    dataset: str = "mimic-iv",
    version: str | None = None,
) -> Path | None:
    """Find one OpenICU concept parquet.

    Expected common layout:
        <concept_root>/<concept>/<version>/<dataset>.parquet

    The function also falls back to a recursive search for '<dataset>.parquet'
    below the concept folder.
    """
    root = Path(concept_root)
    concept_dir = root / openicu_concept
    candidates: list[Path] = []

    if version is not None:
        candidates.append(concept_dir / version / f"{dataset}.parquet")
        candidates.append(concept_dir / version / f"{dataset.replace('-', '_')}.parquet")

    candidates.append(concept_dir / f"{dataset}.parquet")
    candidates.append(concept_dir / f"{dataset.replace('-', '_')}.parquet")

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    if concept_dir.is_dir():
        recursive = sorted(concept_dir.rglob(f"{dataset}.parquet"))
        if recursive:
            return recursive[0]
        recursive = sorted(concept_dir.rglob(f"{dataset.replace('-', '_')}.parquet"))
        if recursive:
            return recursive[0]

    return None


def scan_openicu_concept(path: str | Path) -> pl.LazyFrame:
    """Scan an OpenICU MEDS-like subject-level concept parquet.

    Required columns after normalization:
        subject_id, time, numeric_value
    """
    lf = pl.scan_parquet(path)
    schema = lf.collect_schema()
    required = {"subject_id", "time", "numeric_value"}
    missing = sorted(required - set(schema.names()))
    if missing:
        raise ValueError(f"Concept parquet {path} is missing columns: {missing}")
    return lf.select(
        [
            pl.col("subject_id").cast(pl.Int64),
            pl.col("time"),
            pl.col("numeric_value").cast(pl.Float64),
        ]
    )


def scan_openicu_dynamic_concept(path: str | Path) -> pl.LazyFrame:
    """Scan an already stay/time-indexed OpenICU dynamic concept parquet.

    This is the minimal presentation path: the input concept parquet already
    contains the YAIB-style key columns ``stay_id`` and induced integer ``time``.
    Therefore no ICU stay table is needed and timestamps are not changed.

    Required columns after normalization:
        stay_id, time, numeric_value
    """
    lf = pl.scan_parquet(path)
    schema = lf.collect_schema()
    required = {"stay_id", "time", "numeric_value"}
    missing = sorted(required - set(schema.names()))
    if missing:
        raise ValueError(
            f"Dynamic concept parquet {path} is missing columns: {missing}. "
            "The no-icustays path requires already mapped columns "
            "'stay_id', 'time' and 'numeric_value'."
        )
    return lf.select(
        [
            pl.col("stay_id").cast(pl.Int64),
            pl.col("time").cast(pl.Int64),
            pl.col("numeric_value").cast(pl.Float64),
        ]
    )


def scan_mimic_icustays(path: str | Path) -> pl.LazyFrame:
    """Scan MIMIC-IV icustays.csv.gz and normalize dtypes."""
    lf = pl.scan_csv(path, try_parse_dates=True)
    schema = lf.collect_schema()
    required = {"subject_id", "hadm_id", "stay_id", "intime", "outtime"}
    missing = sorted(required - set(schema.names()))
    if missing:
        raise ValueError(f"ICU stays file {path} is missing columns: {missing}")

    return lf.select(
        [
            pl.col("subject_id").cast(pl.Int64),
            pl.col("hadm_id").cast(pl.Int64),
            pl.col("stay_id").cast(pl.Int64),
            pl.col("intime").cast(pl.Datetime),
            pl.col("outtime").cast(pl.Datetime),
        ]
    )


def _column_name_case_insensitive(names: list[str], requested: str) -> str:
    lookup = {name.lower(): name for name in names}
    try:
        return lookup[requested.lower()]
    except KeyError as exc:
        raise ValueError(f"Column {requested!r} not found; available columns: {names}") from exc


def _time_as_hours(expr: pl.Expr, dtype: pl.DataType, numeric_scale_hours: float) -> pl.Expr:
    if dtype == pl.Datetime or isinstance(dtype, pl.Datetime):
        return expr.dt.epoch("ms").cast(pl.Float64) / 3_600_000.0
    if dtype == pl.Date:
        return expr.cast(pl.Datetime).dt.epoch("ms").cast(pl.Float64) / 3_600_000.0
    if isinstance(dtype, pl.Duration):
        return expr.dt.total_seconds().cast(pl.Float64) / 3600.0
    return expr.cast(pl.Float64) * numeric_scale_hours


def scan_openicu_aumc_stays(
    visit_start_path: str | Path,
    visit_end_path: str | Path,
) -> pl.LazyFrame:
    """Build normalized AUMC ICU stays from OpenICU visit events."""
    start = pl.scan_parquet(visit_start_path).select(
        [
            pl.col("subject_id").cast(pl.Int64),
            pl.col("visit_occurrence_id").cast(pl.Int64).alias("stay_id"),
            (
                pl.col("time").dt.epoch("ms").cast(pl.Float64) / 3_600_000.0
            ).alias("intime_hours"),
        ]
    )
    end = pl.scan_parquet(visit_end_path).select(
        [
            pl.col("subject_id").cast(pl.Int64),
            pl.col("visit_occurrence_id").cast(pl.Int64).alias("stay_id"),
            (
                pl.col("time").dt.epoch("ms").cast(pl.Float64) / 3_600_000.0
            ).alias("outtime_hours"),
        ]
    )

    return start.join(
        end,
        on=["subject_id", "stay_id"],
        how="left",
    )


def scan_dataset_stays(path: str | Path, spec) -> pl.LazyFrame:
    """Read a dataset-specific raw ICU-stay table into normalized hour units."""
    path = Path(path)
    lf = (
        pl.scan_parquet(path)
        if path.suffix == ".parquet"
        else pl.scan_csv(path, try_parse_dates=True)
    )
    schema = lf.collect_schema()
    names = schema.names()
    subject = _column_name_case_insensitive(names, spec.subject_col)
    stay = _column_name_case_insensitive(names, spec.stay_col)

    cols = [
        pl.col(subject).cast(pl.Int64).alias("subject_id"),
        pl.col(stay).cast(pl.Int64).alias("stay_id"),
    ]

    # OpenICU places eICU events on a synthetic datetime axis:
    #
    #   hospital discharge year, January 1 at hospital admission time
    #   - hospitaladmitoffset
    #
    # Because eICU offsets are relative to ICU admission, this reconstructs
    # exactly the admission_timestamp used by the OpenICU eICU configs.
    if spec.dataset in {"eicu", "eicu_demo", "eicu-crd", "eicu-demo"}:
        year = _column_name_case_insensitive(names, "hospitaldischargeyear")
        hospital_time = _column_name_case_insensitive(names, "hospitaladmittime24")
        hospital_offset = _column_name_case_insensitive(names, "hospitaladmitoffset")
        discharge_offset = _column_name_case_insensitive(names, "unitdischargeoffset")

        hospital_admission = pl.concat_str(
            [
                pl.col(year).cast(pl.String),
                pl.lit("-01-01 "),
                pl.col(hospital_time).cast(pl.String),
            ]
        ).str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=True)

        admission = hospital_admission + pl.duration(minutes=-pl.col(hospital_offset))

        admission_hours = admission.dt.epoch("ms").cast(pl.Float64) / 3_600_000.0

        discharge_hours = admission_hours + pl.col(discharge_offset).cast(pl.Float64) / 60.0

        return lf.select(
            [
                pl.col(subject).cast(pl.Int64).alias("subject_id"),
                pl.col(stay).cast(pl.Int64).alias("stay_id"),
                admission_hours.alias("intime_hours"),
                discharge_hours.alias("outtime_hours"),
            ]
        )

    if spec.intime_col is None:
        cols.append(pl.lit(0.0).alias("intime_hours"))
    else:
        intime = _column_name_case_insensitive(names, spec.intime_col)
        cols.append(
            _time_as_hours(pl.col(intime), schema[intime], spec.numeric_time_scale_hours).alias(
                "intime_hours"
            )
        )
    if spec.outtime_col is None:
        cols.append(pl.lit(None, dtype=pl.Float64).alias("outtime_hours"))
    else:
        outtime = _column_name_case_insensitive(names, spec.outtime_col)
        out_expr = _time_as_hours(pl.col(outtime), schema[outtime], spec.numeric_time_scale_hours)
        # SICdb TimeOfStay is a duration; its absolute end is ICUOffset + TimeOfStay.
        if spec.dataset in {"sic", "sicdb"}:
            assert spec.intime_col is not None
            intime_name = _column_name_case_insensitive(names, spec.intime_col)
            intime_expr = _time_as_hours(
                pl.col(intime_name), schema[intime_name], spec.numeric_time_scale_hours
            )
            out_expr = intime_expr + out_expr
        cols.append(out_expr.alias("outtime_hours"))
    return lf.select(cols)


def scan_openicu_subject_concept_hours(
    path: str | Path, numeric_scale_hours: float = 1.0
) -> pl.LazyFrame:
    """Read subject-level OpenICU events and normalize time to numeric hours."""
    lf = pl.scan_parquet(path)
    schema = lf.collect_schema()
    required = {"subject_id", "time", "numeric_value"}
    missing = sorted(required - set(schema.names()))
    if missing:
        raise ValueError(f"Concept parquet {path} is missing columns: {missing}")
    columns = [
        pl.col("subject_id").cast(pl.Int64),
        _time_as_hours(pl.col("time"), schema["time"], numeric_scale_hours).alias("time_hours"),
        pl.col("numeric_value").cast(pl.Float64),
    ]
    if "visit_occurrence_id" in schema.names():
        columns.append(pl.col("visit_occurrence_id").cast(pl.Int64))

    return lf.select(columns)
