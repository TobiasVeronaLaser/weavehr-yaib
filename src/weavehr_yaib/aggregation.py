"""Dataset-level policy for hourly YAIB aggregation metadata."""

from __future__ import annotations

# Datasets for which RICU concept-level aggregation metadata should be used.
#
# This is intentionally independent from native RICU comparison support.
# For example, NWICU and MIMIC-IV Demo are not compared against RICU, but
# their YAIB output may still use RICU's concept-level aggregation semantics.
_RICU_AGGREGATION_DATASETS = {
    "mimic-iv",
    "miiv",
    "mimic-iii",
    "mimic",
    "mimic-iii-demo",
    "mimic_demo",
    "mimic-demo",
    "eicu",
    "eicu-crd",
    "eicu-demo",
    "eicu_demo",
    "hirid",
    "aumc",
    "sic",
    "sicdb",
    "nwicu",
    "mimic-iv-demo",
}


def uses_ricu_aggregation(dataset: str) -> bool:
    """Whether YAIB output should use RICU concept aggregation metadata."""
    return dataset.lower() in _RICU_AGGREGATION_DATASETS
