"""Dataset-specific ICU stay table definitions for autonomous examples."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatasetStaySpec:
    dataset: str
    filenames: tuple[str, ...]
    subject_col: str
    stay_col: str
    intime_col: str | None
    outtime_col: str | None
    numeric_time_scale_hours: float = 1.0
    subject_is_stay: bool = False


_SPECS = {
    "mimic-iv": DatasetStaySpec(
        "mimic-iv", ("icustays.csv.gz",), "subject_id", "stay_id", "intime", "outtime"
    ),
    "miiv": DatasetStaySpec(
        "miiv", ("icustays.csv.gz",), "subject_id", "stay_id", "intime", "outtime"
    ),
    "mimic-iii": DatasetStaySpec(
        "mimic-iii",
        ("ICUSTAYS.csv.gz", "icustays.csv.gz"),
        "SUBJECT_ID",
        "ICUSTAY_ID",
        "INTIME",
        "OUTTIME",
    ),
    "mimic": DatasetStaySpec(
        "mimic",
        ("ICUSTAYS.csv.gz", "icustays.csv.gz"),
        "SUBJECT_ID",
        "ICUSTAY_ID",
        "INTIME",
        "OUTTIME",
    ),
    "mimic_demo": DatasetStaySpec(
        "mimic_demo",
        ("ICUSTAYS.csv.gz", "icustays.csv.gz"),
        "SUBJECT_ID",
        "ICUSTAY_ID",
        "INTIME",
        "OUTTIME",
    ),
    "mimic-iii-demo": DatasetStaySpec(
        "mimic-iii-demo",
        ("ICUSTAYS.csv.gz", "icustays.csv.gz"),
        "SUBJECT_ID",
        "ICUSTAY_ID",
        "INTIME",
        "OUTTIME",
    ),
    "mimic-iv-demo": DatasetStaySpec(
        "mimic-iv-demo", ("icustays.csv.gz",), "subject_id", "stay_id", "intime", "outtime"
    ),
    "eicu": DatasetStaySpec(
        "eicu",
        ("patient.csv.gz",),
        "patienthealthsystemstayid",
        "patientunitstayid",
        None,
        "unitdischargeoffset",
        1 / 60,
        False,
    ),
    "eicu_demo": DatasetStaySpec(
        "eicu_demo",
        ("patient.csv.gz",),
        "patienthealthsystemstayid",
        "patientunitstayid",
        None,
        "unitdischargeoffset",
        1 / 60,
        False,
    ),
    "eicu-crd": DatasetStaySpec(
        "eicu-crd",
        ("patient.csv.gz",),
        "patienthealthsystemstayid",
        "patientunitstayid",
        None,
        "unitdischargeoffset",
        1 / 60,
        False,
    ),
    "eicu-demo": DatasetStaySpec(
        "eicu-demo",
        ("patient.csv.gz",),
        "patienthealthsystemstayid",
        "patientunitstayid",
        None,
        "unitdischargeoffset",
        1 / 60,
        False,
    ),
    "hirid": DatasetStaySpec(
        "hirid", ("general_table.csv",), "patientid", "patientid", "admissiontime", None, 1.0, True
    ),
    "aumc": DatasetStaySpec(
        "aumc",
        ("admissions.csv",),
        "patientid",
        "admissionid",
        "admittedat",
        "dischargedat",
        1 / 3_600_000,
        True,
    ),
    "sicdb": DatasetStaySpec(
        "sicdb", ("cases.csv.gz",), "CaseID", "CaseID", "ICUOffset", "TimeOfStay", 1 / 60, True
    ),
    "sic": DatasetStaySpec(
        "sic", ("cases.csv.gz",), "CaseID", "CaseID", "ICUOffset", "TimeOfStay", 1 / 60, True
    ),
    # NWICU is not a native RICU source; RICU metadata may still be used
    # independently for YAIB aggregation semantics.
    # Without a raw stay table, WeavEHR subject_id is treated as the ICU stay ID.
    "nwicu": DatasetStaySpec("nwicu", (), "subject_id", "subject_id", None, None, 1.0, True),
}


def dataset_stay_spec(dataset: str) -> DatasetStaySpec:
    key = dataset.lower()
    if key not in _SPECS:
        raise ValueError(f"No ICU-stay specification for dataset {dataset!r}.")
    return _SPECS[key]


# Datasets whose WeavEHR concept outputs use other subject/stay identifier spaces
# than the native raw stay table, so the two must not be joined by equal numbers.
_RAW_STAY_TABLE_INCOMPATIBLE = {
    "aumc": (
        "WeavEHR reads AUMC through the AMSTEL OMOP export: its concept events carry OMOP "
        "person_id and visit_occurrence_id, while the native AmsterdamUMCdb admissions table "
        "uses patientid and admissionid. No verified crosswalk links these identifier spaces, "
        "so they are not joined by equal numbers. Omit the stay table (icustays_csv/stays_path, "
        "WEAVEHR_YAIB_AUMC_STAYS, WEAVEHR_YAIB_DATA_ROOT) to derive stays from the WeavEHR "
        "VISIT_START/VISIT_END extraction events instead."
    ),
}
_SIC_RAW_STAY_TABLE_REASON = (
    "WeavEHR uses the SICdb PatientID as subject_id (CaseID only as the case_id extension) and "
    "places events on a per-patient synthetic datetime axis, while the raw cases table spec "
    "uses CaseID as subject and stay ID with case-relative ICUOffset/TimeOfStay. Joining them "
    "would match PatientID to CaseID by equal numbers. Omit the stay table to build one stay "
    "per case from the WeavEHR cases events (requires case_id on the concept events)."
)
_RAW_STAY_TABLE_INCOMPATIBLE["sic"] = _SIC_RAW_STAY_TABLE_REASON
_RAW_STAY_TABLE_INCOMPATIBLE["sicdb"] = _SIC_RAW_STAY_TABLE_REASON


SIC_DATASETS = frozenset({"sic", "sicdb"})

SIC_CASE_ID_HINT = (
    "SIC concept events must carry the SICdb CaseID to be assigned to the right ICU stay "
    "(a patient can have several cases). Keep it via the WeavEHR concept step config:\n"
    "  mapping_configs:\n"
    "    - name: sic\n"
    "      version: <version>\n"
    "      extension_columns:\n"
    '        case_id: col("case_id")'
)


def require_weavehr_stays(dataset: str) -> None:
    """Fail where a dataset's WeavEHR subject_id would be used as stay ID.

    SIC's WeavEHR subject_id is the PatientID, not a stay: stays must be built
    from the WeavEHR cases events (``weavehr_sic_stays``).
    """
    if dataset.lower() in SIC_DATASETS:
        raise ValueError(
            "WeavEHR SIC subject_id is the SICdb PatientID, not an ICU stay ID. Build SIC stays "
            "from the WeavEHR cases events (weavehr_sic_stays / normalized_stays=) instead."
        )


def require_raw_stay_table_compatible(dataset: str) -> None:
    """Fail if a raw stay table cannot be joined to WeavEHR concept events."""
    reason = _RAW_STAY_TABLE_INCOMPATIBLE.get(dataset.lower())
    if reason is not None:
        raise ValueError(f"Cannot map WeavEHR {dataset} concepts onto a raw stay table. {reason}")


def find_dataset_stay_file(dataset: str, explicit: str | Path | None = None) -> Path | None:
    """Resolve a raw ICU-stay table without requiring notebook code changes."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()

    env_specific = os.getenv(f"WEAVEHR_YAIB_{dataset.upper().replace('-', '_')}_STAYS")
    if env_specific:
        return Path(env_specific).expanduser().resolve()

    spec = dataset_stay_spec(dataset)
    if not spec.filenames:
        return None

    roots = []
    for name in ("WEAVEHR_YAIB_DATA_ROOT", "RICU_DATA_PATH"):
        value = os.getenv(name)
        if value:
            roots.append(Path(value).expanduser())
    roots.extend([Path.home() / "ricu_data", Path.home() / "physionet.org" / "files"])

    key = dataset.lower().replace("_", "-")
    hints = {
        "eicu-crd": ("eicu-crd",),
        "eicu": ("eicu-crd",),
        "eicu-demo": ("eicu-crd-demo", "eicu-demo"),
        "eicu_demo": ("eicu-crd-demo", "eicu-demo"),
        "mimic-iv": ("mimiciv", "mimic-iv"),
        "miiv": ("mimiciv", "mimic-iv"),
        "mimic-iv-demo": ("mimic-iv-demo", "mimiciv-demo"),
        "mimic-iii": ("mimiciii", "mimic-iii"),
        "mimic": ("mimiciii", "mimic-iii"),
        "mimic-iii-demo": ("mimic-iii-demo", "mimiciii-demo"),
        "mimic_demo": ("mimic-iii-demo", "mimiciii-demo"),
        "hirid": ("hirid",),
        "aumc": ("aumc",),
        "sic": ("sicdb", "sic"),
        "sicdb": ("sicdb", "sic"),
    }.get(key, (key,))
    wants_demo = "demo" in key

    for root in roots:
        if not root.exists():
            continue
        for filename in spec.filenames:
            matches = sorted(root.rglob(filename))
            if not matches:
                continue

            def score(path: Path) -> tuple[int, int, str]:
                text = str(path).lower().replace("_", "-")
                hint_score = max((len(h) for h in hints if h in text), default=0)
                demo_penalty = 0 if (("demo" in text) == wants_demo) else -100
                return (demo_penalty + hint_score, -len(path.parts), text)

            return max(matches, key=score).resolve()
    return None
