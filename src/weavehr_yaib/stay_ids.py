"""Stay identifier spaces for WeavEHR <-> reference comparisons.

Stay IDs are only matched when both sides use a declared common identifier
space or a crosswalk maps one onto the other. Equal numbers in different
spaces (e.g. RICU AUMC ``admissionid`` vs WeavEHR/AMSTEL OMOP
``visit_occurrence_id``) are never treated as the same stay.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import polars as pl

StayComparisonBasis = Literal["direct_identifier_match", "crosswalk", "side_by_side_only"]
StaySource = Literal[
    "weavehr_visit_events",
    "weavehr_hirid_events",
    "weavehr_sic_cases_events",
    "raw_stay_table",
    "unknown",
]

StayIdVersionAssumption = Literal[
    "same_verified_version",
    "unverified_cross_version_stability",
    "crosswalk",
    "not_applicable",
]

# Identifier spaces are named per dataset, not per version. Whether stay IDs are
# preserved between versions (e.g. MIMIC-IV 2.2 -> 3.1) is not documented in
# the available sources (WeavEHR configs, mimic-code, RICU), so a direct match
# across versions or with an assumed version relies on an unverified assumption
# and is reported as such, with confidence at most "medium".


def stay_id_version_assumption(
    basis: StayComparisonBasis, *, same_verified_version: bool
) -> StayIdVersionAssumption:
    """What a stay match assumes about stay IDs across dataset versions."""
    if basis == "side_by_side_only":
        return "not_applicable"
    if basis == "crosswalk":
        return "crosswalk"
    if same_verified_version:
        return "same_verified_version"
    return "unverified_cross_version_stability"


# ICU stay IDs of RICU sources (``id_cfg$icustay`` in RICU's data-sources.json).
RICU_STAY_ID_SPACES: dict[str, str] = {
    "miiv": "mimic-iv:icustays.stay_id",
    "mimic": "mimic-iii:icustays.icustay_id",
    "mimic_demo": "mimic-iii-demo:icustays.icustay_id",
    "eicu": "eicu-crd:patient.patientunitstayid",
    "eicu_demo": "eicu-demo:patient.patientunitstayid",
    "hirid": "hirid:general.patientid",
    "aumc": "aumcdb:admissions.admissionid",
    "sic": "sicdb:cases.caseid",
}

# Stay IDs taken from a raw (native) stay table, see ``stays.py``.
_RAW_STAY_TABLE_SPACES: dict[str, str] = {
    "mimic-iv": "mimic-iv:icustays.stay_id",
    "mimic-iv-demo": "mimic-iv-demo:icustays.stay_id",
    "mimic-iii": "mimic-iii:icustays.icustay_id",
    "mimic-iii-demo": "mimic-iii-demo:icustays.icustay_id",
    "eicu-crd": "eicu-crd:patient.patientunitstayid",
    "eicu-demo": "eicu-demo:patient.patientunitstayid",
    # Same native patientid column as WeavEHR's HiRID subject_id.
    "hirid": "hirid:general.patientid",
    # AUMC and SIC are deliberately absent: their raw stay tables use other
    # identifier spaces than WeavEHR's concept events (see stays.py).
}

# Stay IDs derived from WeavEHR extraction events.
_WEAVEHR_EVENT_STAY_SPACES: dict[tuple[str, str], str] = {
    ("aumc", "weavehr_visit_events"): "omop:visit_occurrence.visit_occurrence_id",
    ("hirid", "weavehr_hirid_events"): "hirid:general.patientid",
    # WeavEHR's case_id extension is the native SICdb cases.CaseID.
    ("sic", "weavehr_sic_cases_events"): "sicdb:cases.caseid",
    ("sicdb", "weavehr_sic_cases_events"): "sicdb:cases.caseid",
}


def weavehr_stay_id_space(dataset: str, stay_source: StaySource) -> str | None:
    """Identifier space of the stay IDs in a WeavEHR wide export, if known."""
    dataset = dataset.lower()
    if stay_source == "raw_stay_table":
        return _RAW_STAY_TABLE_SPACES.get(dataset)
    return _WEAVEHR_EVENT_STAY_SPACES.get((dataset, stay_source))


def load_stay_crosswalk(crosswalk: str | Path | pl.DataFrame) -> pl.DataFrame:
    """Read a one-to-one ``reference_stay_id`` -> ``weavehr_stay_id`` crosswalk."""
    df = crosswalk if isinstance(crosswalk, pl.DataFrame) else pl.read_csv(crosswalk)
    missing = {"reference_stay_id", "weavehr_stay_id"} - set(df.columns)
    if missing:
        raise ValueError(f"Stay crosswalk is missing columns: {sorted(missing)}")
    df = (
        df.select(
            pl.col("reference_stay_id").cast(pl.Int64), pl.col("weavehr_stay_id").cast(pl.Int64)
        )
        .drop_nulls()
        .unique()
    )
    for column in ("reference_stay_id", "weavehr_stay_id"):
        if df[column].is_duplicated().any():
            raise ValueError(f"Stay crosswalk must be one-to-one; duplicated {column} values.")
    return df


@dataclass(frozen=True)
class StayIdComparison:
    """Stay identifier spaces of both sides and an optional crosswalk."""

    weavehr_space: str | None
    reference_space: str | None
    crosswalk: pl.DataFrame | None = None

    @property
    def basis(self) -> StayComparisonBasis:
        if self.crosswalk is not None:
            return "crosswalk"
        if self.weavehr_space is not None and self.weavehr_space == self.reference_space:
            return "direct_identifier_match"
        return "side_by_side_only"

    @property
    def matchable(self) -> bool:
        return self.basis != "side_by_side_only"

    def to_weavehr_ids(self, df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Translate reference ``stay_id`` values into the WeavEHR space.

        Returns the translated rows and the reference stay IDs without a
        crosswalk entry. Without a crosswalk the frame is returned unchanged.
        """
        if self.crosswalk is None:
            return df, df.select("stay_id").clear()
        mapped = df.join(
            self.crosswalk, left_on="stay_id", right_on="reference_stay_id", how="inner"
        )
        unmapped = df.join(
            self.crosswalk, left_on="stay_id", right_on="reference_stay_id", how="anti"
        ).select("stay_id")
        return (
            mapped.drop("stay_id").rename({"weavehr_stay_id": "stay_id"}).select(df.columns),
            unmapped.unique(),
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "weavehr_stay_id_space": self.weavehr_space,
            "reference_stay_id_space": self.reference_space,
            "stay_comparison_basis": self.basis,
        }
