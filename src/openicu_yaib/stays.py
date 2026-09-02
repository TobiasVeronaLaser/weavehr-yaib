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
    # Without a raw stay table, OpenICU subject_id is treated as the ICU stay ID.
    "nwicu": DatasetStaySpec("nwicu", (), "subject_id", "subject_id", None, None, 1.0, True),
}


def dataset_stay_spec(dataset: str) -> DatasetStaySpec:
    key = dataset.lower()
    if key not in _SPECS:
        raise ValueError(f"No ICU-stay specification for dataset {dataset!r}.")
    return _SPECS[key]


def find_dataset_stay_file(dataset: str, explicit: str | Path | None = None) -> Path | None:
    """Resolve a raw ICU-stay table without requiring notebook code changes."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()

    env_specific = os.getenv(f"OPENICU_YAIB_{dataset.upper().replace('-', '_')}_STAYS")
    if env_specific:
        return Path(env_specific).expanduser().resolve()

    spec = dataset_stay_spec(dataset)
    if not spec.filenames:
        return None

    roots = []
    for name in ("OPENICU_YAIB_DATA_ROOT", "RICU_DATA_PATH"):
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
