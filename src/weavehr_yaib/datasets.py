"""Dataset registry used by the one-notebook-per-dataset YAIB workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSpec:
    """WeavEHR dataset name and optional matching RICU source.

    ``weavehr_bundled`` records whether current WeavEHR ships dataset configs
    (``configs/datasets/<name>``) for this dataset. Datasets without bundled
    configs need custom WeavEHR extraction/concept configs before their concept
    outputs exist; this package only consumes those outputs.
    """

    name: str
    ricu_source: str | None
    aliases: tuple[str, ...] = ()
    weavehr_bundled: bool = True

    @property
    def has_ricu(self) -> bool:
        return self.ricu_source is not None


DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec("aumc", "aumc"),
    DatasetSpec("eicu-crd", "eicu", ("eicu",)),
    DatasetSpec("eicu-demo", "eicu_demo", ("eicu_demo",)),
    DatasetSpec("hirid", "hirid"),
    # Current WeavEHR bundles no MIMIC-III configs; these workflows require
    # custom WeavEHR dataset configs.
    DatasetSpec("mimic-iii", "mimic", ("mimic",), weavehr_bundled=False),
    DatasetSpec(
        "mimic-iii-demo", "mimic_demo", ("mimic_demo", "mimic-demo"), weavehr_bundled=False
    ),
    DatasetSpec("mimic-iv", "miiv", ("miiv",)),
    # ricu has no separate built-in/source entry corresponding to WeavEHR mimic-iv-demo.
    DatasetSpec("mimic-iv-demo", None),
    DatasetSpec("nwicu", None),
    DatasetSpec("sic", "sic", ("sicdb",)),
)


def dataset_spec(dataset: str) -> DatasetSpec:
    """Resolve canonical WeavEHR dataset metadata from a name or alias."""
    key = dataset.lower()
    for spec in DATASETS:
        if key == spec.name or key in spec.aliases:
            return spec
    supported = ", ".join(spec.name for spec in DATASETS)
    raise ValueError(f"Unsupported dataset {dataset!r}; expected one of: {supported}")
