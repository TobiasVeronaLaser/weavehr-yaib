"""Dataset-specific ICU stay table definitions for autonomous examples."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .versions import versions_equal


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
# Datasets whose stays are rebuilt from WeavEHR extraction events by default.
EVENT_STAY_DATASETS = frozenset({"aumc", "hirid", *SIC_DATASETS})

SIC_CASE_ID_HINT = (
    "SIC concept events must carry the SICdb CaseID to be assigned to the right ICU stay "
    "(a patient can have several cases). Keep it via the WeavEHR concept step config:\n"
    "  mapping_configs:\n"
    "    - name: sic\n"
    "      version: <version>\n"
    "      extension_columns:\n"
    '        case_id: col("case_id")'
)


# Datasets whose WeavEHR subject_id must not be used as stay ID with event
# times taken as stay-relative hours: their WeavEHR event times are absolute.
_EVENT_STAYS_REQUIRED = {
    "sic": (
        "WeavEHR SIC subject_id is the SICdb PatientID, not an ICU stay ID. Build SIC stays "
        "from the WeavEHR cases events (weavehr_sic_stays / normalized_stays=) instead."
    ),
    "hirid": (
        "WeavEHR HiRID event times are absolute timestamps, not hours since ICU admission. "
        "Build HiRID stays from the WeavEHR ICU_ADMISSION/OBSERVATION events "
        "(weavehr_hirid_stays / normalized_stays=) or pass the raw general table."
    ),
}
_EVENT_STAYS_REQUIRED["sicdb"] = _EVENT_STAYS_REQUIRED["sic"]


def require_weavehr_stays(dataset: str) -> None:
    """Fail where a dataset's WeavEHR subject_id would be used as stay ID.

    For these datasets the subject-as-stay fallback would either use a patient
    ID as stay ID (SIC) or treat absolute event times as stay-relative hours
    (SIC, HiRID). Stays must come from WeavEHR events or a compatible table.
    """
    reason = _EVENT_STAYS_REQUIRED.get(dataset.lower())
    if reason is not None:
        raise ValueError(reason)


def require_raw_stay_table_compatible(dataset: str) -> None:
    """Fail if a raw stay table cannot be joined to WeavEHR concept events."""
    reason = _RAW_STAY_TABLE_INCOMPATIBLE.get(dataset.lower())
    if reason is not None:
        raise ValueError(f"Cannot map WeavEHR {dataset} concepts onto a raw stay table. {reason}")


StayTableSelection = Literal["explicit", "environment", "discovered"]

_VERSION_DIR = re.compile(r"^v?(?P<version>\d+(?:\.\d+)+)$")
# Dataset folder named with its version, e.g. ``mimic-iv-2.2`` (PhysioNet ZIP).
_VERSIONED_FOLDER = re.compile(r"^(?P<name>.+?)-v?(?P<version>\d+(?:\.\d+)+)$")

# Name fragments of dataset folders (PhysioNet wget and ZIP layouts), per
# dataset family. Only versions attached to such folders are dataset versions.
_DATASET_FOLDER_TOKENS: dict[str, tuple[str, ...]] = {
    "mimic-iv": ("mimiciv", "mimic-iv"),
    "mimic-iii": ("mimiciii", "mimic-iii"),
    "eicu": ("eicu",),
    "hirid": ("hirid",),
    "aumc": ("aumc", "amsterdamumcdb"),
    "sic": ("sicdb",),
}


def _dataset_folder_tokens(dataset: str | None) -> tuple[str, ...]:
    if dataset is None:
        return tuple(t for tokens in _DATASET_FOLDER_TOKENS.values() for t in tokens)
    key = dataset.lower().replace("_", "-")
    if key.startswith(("mimic-iv", "miiv")):
        family = "mimic-iv"
    elif key.startswith("mimic"):
        family = "mimic-iii"
    elif key.startswith("eicu"):
        family = "eicu"
    elif key.startswith("sic"):
        family = "sic"
    else:
        family = key
    return _DATASET_FOLDER_TOKENS.get(family, (key,))


@dataclass(frozen=True)
class StayTable:
    """A raw stay table and the dataset version its path states, if any."""

    path: Path
    version: str | None
    selection: StayTableSelection

    def as_provenance(self) -> dict[str, str | None]:
        return {
            "stay_table_path": str(self.path),
            "stay_table_version": self.version,
            "stay_table_selection": self.selection,
        }


def path_dataset_version(path: str | Path, dataset: str | None = None) -> str | None:
    """Dataset version stated by a stay-table path, if any.

    Only versions attached to a folder naming the dataset count: the folder
    directly below it (``.../mimiciv/2.2/icu/...``) or a version suffix of the
    folder itself (``.../mimic-iv-2.2/...``,
    ``.../eicu-collaborative-research-database-2.0/...``). Version-like
    directories unrelated to the dataset (``/srv/1.0/ricu_data/miiv/...``) are
    ignored. The innermost match wins.
    """
    tokens = _dataset_folder_tokens(dataset)
    parts = [part.lower().replace("_", "-") for part in Path(path).parts]
    found: str | None = None
    for i, part in enumerate(parts):
        folder = _VERSIONED_FOLDER.match(part)
        if folder and any(t in folder.group("name") for t in tokens):
            found = folder.group("version")
        elif any(t in part for t in tokens) and i + 1 < len(parts):
            version_dir = _VERSION_DIR.match(parts[i + 1])
            if version_dir:
                found = version_dir.group("version")
    return found


def _checked(table: StayTable, dataset: str, dataset_version: str | None) -> StayTable:
    if versions_equal(table.version, dataset_version) is False:
        raise ValueError(
            f"Stay table {table.path} is for {dataset} version {table.version!r}, but the "
            f"WeavEHR concepts are version {dataset_version!r}."
        )
    return table


def resolve_dataset_stay_table(
    dataset: str,
    *,
    explicit: str | Path | None = None,
    dataset_version: str | None = None,
) -> StayTable | None:
    """Resolve a raw ICU-stay table, never mixing dataset versions.

    Order: ``explicit``, ``WEAVEHR_YAIB_<DATASET>_STAYS``, then discovery below
    ``WEAVEHR_YAIB_DATA_ROOT``, ``RICU_DATA_PATH``, ``~/ricu_data`` and
    ``~/physionet.org/files``. Explicit and environment paths are accepted but
    must not state another version than ``dataset_version`` (see
    :func:`path_dataset_version`). Discovery only selects a table whose path
    states ``dataset_version``, searching all roots before failing; without a
    known version it fails if candidates of several versions exist. Ambiguity raises
    ``ValueError``: pass the stay table explicitly then.
    """
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        return _checked(
            StayTable(path, path_dataset_version(path, dataset), "explicit"),
            dataset,
            dataset_version,
        )

    env_specific = os.getenv(f"WEAVEHR_YAIB_{dataset.upper().replace('-', '_')}_STAYS")
    if env_specific:
        path = Path(env_specific).expanduser().resolve()
        return _checked(
            StayTable(path, path_dataset_version(path, dataset), "environment"),
            dataset,
            dataset_version,
        )

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

    def hint_score(path: Path) -> int:
        text = str(path).lower().replace("_", "-")
        return max((len(h) for h in hints if h in text), default=0)

    def score(path: Path) -> tuple[int, int, str]:
        return (hint_score(path), -len(path.parts), str(path).lower())

    # With a known version every root is searched for a table of that version
    # before failing; without one, the first root with candidates decides.
    seen: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for filename in spec.filenames:
            matches = [p for p in root.rglob(filename) if ("demo" in str(p).lower()) == wants_demo]
            if not matches:
                continue
            # Prefer paths naming the dataset when there are any.
            if any(hint_score(p) for p in matches):
                matches = [p for p in matches if hint_score(p)]
            by_version = {p: path_dataset_version(p, dataset) for p in matches}
            if dataset_version is not None:
                hits = [p for p, v in by_version.items() if versions_equal(v, dataset_version)]
                if hits:
                    return StayTable(max(hits, key=score).resolve(), dataset_version, "discovered")
                seen.extend(matches)
                continue
            distinct = {v for v in by_version.values()}
            if len(distinct) > 1:
                raise ValueError(
                    f"Stay tables of several {dataset} versions found below {root}: "
                    f"{sorted(map(str, matches))}. Select the WeavEHR dataset version or "
                    "pass the stay table explicitly."
                )
            best = max(matches, key=score)
            return StayTable(best.resolve(), by_version[best], "discovered")
    if seen:
        raise ValueError(
            f"No {' / '.join(spec.filenames)} for {dataset} version {dataset_version!r} found; "
            f"candidates of other or unknown versions: {sorted(map(str, seen))}. Pass the stay "
            "table explicitly."
        )
    return None


def find_dataset_stay_file(
    dataset: str, explicit: str | Path | None = None, dataset_version: str | None = None
) -> Path | None:
    """Path of :func:`resolve_dataset_stay_table`, or ``None``."""
    table = resolve_dataset_stay_table(dataset, explicit=explicit, dataset_version=dataset_version)
    return None if table is None else table.path
