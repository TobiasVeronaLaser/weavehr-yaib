"""Input helpers for WeavEHR concept parquets and MIMIC-IV ICU stays."""

from __future__ import annotations

from pathlib import Path

import polars as pl

# Optional concept-output column holding the WeavEHR dataset version, added via
# the concept step's ``extension_columns: {dataset_version: col("version")}``.
DATASET_VERSION_COLUMN = "dataset_version"


# Concept-event columns linking an event to its exact stay, by dataset:
# AUMC OMOP visit_occurrence_id, SICdb CaseID (WeavEHR extension ``case_id``).
# They are only present if the concept step keeps them in ``extension_columns``.
STAY_LINK_COLUMNS = ("visit_occurrence_id", "case_id")


def require_concept_column(concept_files: list[Path], column: str, hint: str) -> None:
    """Fail if any concept parquet lacks ``column``."""
    for path in concept_files:
        if column not in pl.scan_parquet(path).collect_schema().names():
            raise ValueError(f"{path} has no {column!r} column.\n{hint}")


def stay_link_column(names: list[str]) -> str | None:
    """The stay-link column present in a concept-event schema, if any."""
    return next((c for c in STAY_LINK_COLUMNS if c in names), None)


def filter_dataset_version(lf: pl.LazyFrame, dataset_version: str | None) -> pl.LazyFrame:
    """Keep rows of one dataset version when the concept output records it.

    Without the column the version was resolved from the project layout, which
    guarantees a single version, so there is nothing to filter.
    """
    if dataset_version is None or DATASET_VERSION_COLUMN not in lf.collect_schema().names():
        return lf
    return lf.filter(pl.col(DATASET_VERSION_COLUMN).cast(pl.String) == dataset_version)


def find_concept_file(
    concept_root: str | Path,
    weavehr_concept: str,
    *,
    dataset: str = "mimic-iv",
    version: str | None = None,
) -> Path | None:
    """Find one WeavEHR concept parquet.

    Expected common layout:
        <concept_root>/<concept>/<version>/<dataset>.parquet

    The function also falls back to a recursive search for '<dataset>.parquet'
    below the concept folder.
    """
    root = Path(concept_root)
    concept_dir = root / weavehr_concept
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


def scan_weavehr_concept(path: str | Path, *, dataset_version: str | None = None) -> pl.LazyFrame:
    """Scan a WeavEHR MEDS-like subject-level concept parquet.

    Required columns after normalization:
        subject_id, time, numeric_value
    """
    lf = filter_dataset_version(pl.scan_parquet(path), dataset_version)
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


def scan_weavehr_dynamic_concept(
    path: str | Path, *, dataset_version: str | None = None
) -> pl.LazyFrame:
    """Scan an already stay/time-indexed WeavEHR dynamic concept parquet.

    This is the minimal presentation path: the input concept parquet already
    contains the YAIB-style key columns ``stay_id`` and induced integer ``time``.
    Therefore no ICU stay table is needed and timestamps are not changed.

    Required columns after normalization:
        stay_id, time, numeric_value
    """
    lf = filter_dataset_version(pl.scan_parquet(path), dataset_version)
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


def scan_weavehr_aumc_stays(
    visit_start_path: str | Path,
    visit_end_path: str | Path,
) -> pl.LazyFrame:
    """Build normalized AUMC ICU stays from WeavEHR visit events.

    WeavEHR extracts AUMC through the inherited OMOP ``visit_occurrence`` table;
    ``VISIT_START``/``VISIT_END`` carry ``visit_occurrence_id`` as an extension
    column, which becomes the stay ID.
    """
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



def scan_weavehr_hirid_stays(
    admission_path: str | Path,
    observations_path: str | Path,
) -> pl.LazyFrame:
    """Build HiRID ICU stay windows matching RICU semantics.

    RICU uses ICU admission as the start and the latest observation timestamp
    per patient as the stay end.
    """
    admission = (
        pl.scan_parquet(admission_path)
        .select(
            [
                pl.col("subject_id").cast(pl.Int64),
                (
                    pl.col("time").dt.epoch("ms").cast(pl.Float64)
                    / 3_600_000.0
                ).alias("intime_hours"),
            ]
        )
        .unique(subset=["subject_id"])
    )

    observation_end = (
        pl.scan_parquet(observations_path)
        .group_by("subject_id")
        .agg(
            (
                pl.col("time").max().dt.epoch("ms").cast(pl.Float64)
                / 3_600_000.0
            ).alias("outtime_hours")
        )
    )

    return (
        admission.join(observation_end, on="subject_id", how="left")
        .with_columns(pl.col("subject_id").alias("stay_id"))
        .select("subject_id", "stay_id", "intime_hours", "outtime_hours")
    )


def scan_weavehr_sic_stays(
    admission_path: str | Path,
    observations_path: str | Path,
) -> pl.LazyFrame:
    """Build SIC ICU stays (one per case) from WeavEHR ``cases`` events.

    WeavEHR places all SICdb events of a patient on one synthetic axis,
    ``Jan 1 of the first admission year + OffsetAfterFirstAdmission + Offset``
    (seconds), and emits ``ICU_ADMISSION`` at ``Offset`` 0 of each case, with
    ``case_id`` (SICdb ``CaseID``) as extension. The stay is the case: it starts
    at its ``ICU_ADMISSION`` event and ends at its latest ``OBSERVATION``
    (``data_float_h``) event, because WeavEHR does not extract ``TimeOfStay``.
    Both times are on the same axis as the concept events.
    """

    def epoch_hours(expr: pl.Expr) -> pl.Expr:
        return expr.dt.epoch("ms").cast(pl.Float64) / 3_600_000.0

    admission = (
        pl.scan_parquet(admission_path)
        .select(
            pl.col("subject_id").cast(pl.Int64),
            pl.col("case_id").cast(pl.Int64).alias("stay_id"),
            epoch_hours(pl.col("time")).alias("intime_hours"),
        )
        .unique(subset=["stay_id"])
    )
    observation_end = (
        pl.scan_parquet(observations_path)
        .group_by(pl.col("case_id").cast(pl.Int64).alias("stay_id"))
        .agg(epoch_hours(pl.col("time").max()).alias("outtime_hours"))
    )
    return admission.join(observation_end, on="stay_id", how="left").select(
        "subject_id", "stay_id", "intime_hours", "outtime_hours"
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

    # WeavEHR places eICU events on a synthetic datetime axis:
    #
    #   hospital discharge year, January 1 at hospital admission time
    #   - hospitaladmitoffset
    #
    # Because eICU offsets are relative to ICU admission, this reconstructs
    # exactly the admission_timestamp used by the WeavEHR eICU configs.
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


def scan_weavehr_subject_concept_hours(
    path: str | Path, numeric_scale_hours: float = 1.0, *, dataset_version: str | None = None
) -> pl.LazyFrame:
    """Read subject-level WeavEHR events and normalize time to numeric hours.

    Stay-link columns (``visit_occurrence_id`` for AUMC, ``case_id`` for SIC)
    are kept when present so events can be mapped to the exact stay. WeavEHR
    concept outputs only contain them if the concept step lists them under
    ``extension_columns``, and writes them as strings, hence the cast to Int64.
    """
    lf = filter_dataset_version(pl.scan_parquet(path), dataset_version)
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
    for link in STAY_LINK_COLUMNS:
        if link in schema.names():
            columns.append(pl.col(link).cast(pl.Int64))

    return lf.select(columns)
