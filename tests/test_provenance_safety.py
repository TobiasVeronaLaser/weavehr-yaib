"""Version-safe stay tables, config/CLI provenance and stale provenance detection."""

import gzip
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from weavehr_yaib import build_and_write_yaib_wide, build_and_write_yaib_wide_for_dataset
from weavehr_yaib.cli import main as cli_main
from weavehr_yaib.pipeline import write_mortality_dynamic_wide_from_config
from weavehr_yaib.stays import path_dataset_version, resolve_dataset_stay_table
from weavehr_yaib.versions import (
    StaleProvenanceError,
    read_provenance_field,
    read_weavehr_provenance,
)
from weavehr_yaib.workflow import resolve_comparison_versions


@pytest.fixture(autouse=True)
def isolated_data_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Discovery only sees ``tmp_path/data``."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("RICU_DATA_PATH", "WEAVEHR_YAIB_ICUSTAYS_CSV", "WEAVEHR_YAIB_MIMIC_IV_STAYS"):
        monkeypatch.delenv(name, raising=False)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("WEAVEHR_YAIB_DATA_ROOT", str(data))
    return data


def _icustays(path: Path, stay_id: int) -> Path:
    """MIMIC-IV icustays.csv.gz with one 10-hour stay of subject 1."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as handle:
        handle.write("subject_id,hadm_id,stay_id,intime,outtime\n")
        handle.write(f"1,10,{stay_id},2150-01-01 00:00:00,2150-01-01 10:00:00\n")
    return path


def _stay_tables(data: Path) -> dict[str, Path]:
    """Stay tables of MIMIC-IV 2.2 (stay 100), 3.1 (stay 300) and the 2.2 demo."""
    _icustays(data / "physionet.org/files/mimic-iv-demo/2.2/icu/icustays.csv.gz", 900)
    return {
        version: _icustays(data / f"physionet.org/files/mimiciv/{version}/icu/icustays.csv.gz", sid)
        for version, sid in (("2.2", 100), ("3.1", 300))
    }


def _project(tmp_path: Path, versions: list[str] | None = None) -> Path:
    """MIMIC-IV 2.2 WeavEHR project with one heart-rate event per concept row.

    ``versions`` adds a ``dataset_version`` column with one row per version
    (values 80, 81, ...).
    """
    root = tmp_path / "project"
    for sub in ("datasets", "configs", "workspace/extraction/mimic-iv/2.2"):
        (root / sub).mkdir(parents=True)
    n = len(versions) if versions else 1
    df = pl.DataFrame(
        {
            "subject_id": [1] * n,
            "time": pl.Series([datetime(2150, 1, 1, 1, 30)] * n, dtype=pl.Datetime("us")),
            "numeric_value": pl.Series([80.0 + i for i in range(n)], dtype=pl.Float32),
        }
    )
    if versions:
        df = df.with_columns(pl.Series("dataset_version", versions))
    path = root / "workspace/concept/heart_rate/1.0.0/mimic-iv.parquet"
    path.parent.mkdir(parents=True)
    df.write_parquet(path)
    return root


def _export(project: Path, tmp_path: Path, **kwargs):
    concept_dict = tmp_path / "concept-dict.json"
    concept_dict.write_text("{}")
    return build_and_write_yaib_wide_for_dataset(
        dataset="mimic-iv",
        max_hours=168,
        output_root=tmp_path / "out",
        concept_root=project / "workspace/concept",
        ricu_concept_dict=concept_dict,
        dynamic_vars=["hr"],
        **kwargs,
    )


# ---------------------------------------------------------------------------
# High 1: raw stay-table discovery is dataset-version safe
# ---------------------------------------------------------------------------


def test_discovery_selects_the_stay_table_of_the_requested_version(
    isolated_data_roots: Path,
) -> None:
    tables = _stay_tables(isolated_data_roots)
    table = resolve_dataset_stay_table("mimic-iv", dataset_version="2.2")
    assert table is not None
    assert (table.path, table.version, table.selection) == (
        tables["2.2"].resolve(),
        "2.2",
        "discovered",
    )


def test_discovery_without_version_fails_across_versions(isolated_data_roots: Path) -> None:
    _stay_tables(isolated_data_roots)
    with pytest.raises(ValueError, match="several mimic-iv versions"):
        resolve_dataset_stay_table("mimic-iv")
    with pytest.raises(ValueError, match="version '3.0'"):
        resolve_dataset_stay_table("mimic-iv", dataset_version="3.0")


def test_explicit_stay_table_of_another_version_is_rejected(isolated_data_roots: Path) -> None:
    tables = _stay_tables(isolated_data_roots)
    with pytest.raises(ValueError, match="is for mimic-iv version '3.1'"):
        resolve_dataset_stay_table("mimic-iv", explicit=tables["3.1"], dataset_version="2.2")


def test_wide_export_uses_the_stay_table_of_the_resolved_version(
    tmp_path: Path, isolated_data_roots: Path
) -> None:
    _stay_tables(isolated_data_roots)
    result = _export(_project(tmp_path), tmp_path)

    # Stay 100 comes from the 2.2 table; the 3.1 table (stay 300) is not used.
    assert set(pl.read_parquet(result.output_path)["stay_id"]) == {100}
    assert read_provenance_field(result.output_path, "stay_table_version") == "2.2"
    assert read_provenance_field(result.output_path, "stay_table_selection") == "discovered"
    assert read_provenance_field(result.output_path, "stay_id_space") == "mimic-iv:icustays.stay_id"


# ---------------------------------------------------------------------------
# High 2: config/CLI path resolves the dataset version and writes provenance
# ---------------------------------------------------------------------------


def _config(tmp_path: Path, project: Path, stays: Path, dataset_version: str | None) -> Path:
    (tmp_path / "vars.yml").write_text("dynamic_vars: [hr]\n")
    path = tmp_path / "weavehr_yaib.yml"
    version_line = f'  dataset_version: "{dataset_version}"\n' if dataset_version else ""
    path.write_text(
        "concepts:\n"
        f"  path: {project / 'workspace/concept'}\n"
        "  dataset: mimic-iv\n"
        "  version: 1.0.0\n"
        f"{version_line}"
        f"icustays_csv: {stays}\n"
        "yaib:\n"
        f"  dynamic_vars: {tmp_path / 'vars.yml'}\n"
        "grid:\n"
        "  include: false\n"
        "output:\n"
        f"  path: {tmp_path / 'cfg_out.parquet'}\n"
    )
    return path


def test_config_path_requires_a_dataset_version_when_several(
    tmp_path: Path, isolated_data_roots: Path
) -> None:
    tables = _stay_tables(isolated_data_roots)
    project = _project(tmp_path, ["2.2", "3.1"])
    with pytest.raises(ValueError, match="several dataset versions"):
        write_mortality_dynamic_wide_from_config(_config(tmp_path, project, tables["2.2"], None))


def test_config_path_selects_version_and_writes_provenance(
    tmp_path: Path, isolated_data_roots: Path
) -> None:
    tables = _stay_tables(isolated_data_roots)
    project = _project(tmp_path, ["2.2", "3.1"])
    out = write_mortality_dynamic_wide_from_config(_config(tmp_path, project, tables["2.2"], "2.2"))

    # Only the 2.2 row (80) is aggregated, not the mean with the 3.1 row (81).
    assert pl.read_parquet(out)["hr"].to_list() == [80.0]
    version = read_weavehr_provenance(out)
    assert version is not None and (version.version, version.source) == ("2.2", "explicit")
    assert read_provenance_field(out, "stay_table_version") == "2.2"
    assert read_provenance_field(out, "stay_source") == "raw_stay_table"


def test_cli_dataset_version_flag(tmp_path: Path, isolated_data_roots: Path) -> None:
    tables = _stay_tables(isolated_data_roots)
    project = _project(tmp_path, ["2.2", "3.1"])
    out = tmp_path / "cli.parquet"
    args = [
        "--concept-root",
        str(project / "workspace/concept"),
        "--icustays-csv",
        str(tables["3.1"]),
        "--output",
        str(out),
        "--no-grid",
    ]
    with pytest.raises(ValueError, match="several dataset versions"):
        cli_main(args)

    cli_main([*args, "--dataset-version", "3.1"])
    assert pl.read_parquet(out)["hr"].to_list() == [81.0]
    assert read_weavehr_provenance(out).version == "3.1"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Medium 4: stale or mismatched provenance is never trusted
# ---------------------------------------------------------------------------


def test_low_level_rewrite_removes_the_old_provenance(
    tmp_path: Path, isolated_data_roots: Path
) -> None:
    tables = _stay_tables(isolated_data_roots)
    project = _project(tmp_path)
    result = _export(project, tmp_path)
    assert read_weavehr_provenance(result.output_path) is not None

    build_and_write_yaib_wide(
        concept_root=project / "workspace/concept",
        icustays_csv=tables["3.1"],
        ricu_concept_dict=tmp_path / "concept-dict.json",
        output_path=result.output_path,
        dynamic_vars=["hr"],
    )

    assert read_weavehr_provenance(result.output_path) is None
    versions = resolve_comparison_versions(
        dataset="mimic-iv",
        weavehr_wide_path=result.output_path,
        ricu_dynamic_path=tmp_path / "out/ricu_dynamic_vars_miiv.parquet",
    )
    assert versions.weavehr.source == "unknown"


def test_provenance_of_replaced_parquet_is_rejected(
    tmp_path: Path, isolated_data_roots: Path
) -> None:
    _stay_tables(isolated_data_roots)
    result = _export(_project(tmp_path), tmp_path)
    # Some other writer replaces the parquet but leaves the sidecar behind.
    pl.read_parquet(result.output_path).write_parquet(result.output_path)

    with pytest.raises(StaleProvenanceError, match="stale or mismatched"):
        read_weavehr_provenance(result.output_path)
    with pytest.raises(StaleProvenanceError):
        resolve_comparison_versions(
            dataset="mimic-iv",
            weavehr_wide_path=result.output_path,
            ricu_dynamic_path=tmp_path / "out/ricu_dynamic_vars_miiv.parquet",
        )


def test_provenance_of_another_dataset_is_rejected(
    tmp_path: Path, isolated_data_roots: Path
) -> None:
    _stay_tables(isolated_data_roots)
    result = _export(_project(tmp_path), tmp_path)
    with pytest.raises(ValueError, match="built for WeavEHR dataset 'mimic-iv'"):
        resolve_comparison_versions(
            dataset="eicu-crd",
            weavehr_wide_path=result.output_path,
            ricu_dynamic_path=tmp_path / "out/ricu_dynamic_vars_eicu.parquet",
        )


# ---------------------------------------------------------------------------
# Dataset version stated by stay-table paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dataset", "path", "expected"),
    [
        # PhysioNet wget layout
        ("mimic-iv", "/d/physionet.org/files/mimiciv/2.2/icu/icustays.csv.gz", "2.2"),
        # PhysioNet ZIP layout
        ("mimic-iv", "/d/mimic-iv-2.2/icu/icustays.csv.gz", "2.2"),
        ("eicu-crd", "/d/eicu-collaborative-research-database-2.0/patient.csv.gz", "2.0"),
        # Version-like ancestor unrelated to the dataset
        ("mimic-iv", "/srv/1.0/ricu_data/miiv/icustays.csv.gz", None),
        ("mimic-iv", "/srv/1.0/physionet.org/files/mimiciv/3.1/icu/icustays.csv.gz", "3.1"),
    ],
)
def test_path_dataset_version(dataset: str, path: str, expected: str | None) -> None:
    assert path_dataset_version(path, dataset) == expected


def test_explicit_zip_layout_table_of_another_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="is for mimic-iv version '3.1'"):
        resolve_dataset_stay_table(
            "mimic-iv", explicit="/d/mimic-iv-3.1/icu/icustays.csv.gz", dataset_version="2.2"
        )


def test_unrelated_versioned_ancestor_does_not_reject_an_explicit_table(tmp_path: Path) -> None:
    path = tmp_path / "srv/1.0/ricu_data/miiv/icustays.csv.gz"
    table = resolve_dataset_stay_table("mimic-iv", explicit=path, dataset_version="2.2")
    assert table is not None and table.version is None


def test_discovery_finds_zip_layout_of_the_requested_version(isolated_data_roots: Path) -> None:
    expected = _icustays(isolated_data_roots / "mimic-iv-2.2/icu/icustays.csv.gz", 100)
    _icustays(isolated_data_roots / "mimic-iv-3.1/icu/icustays.csv.gz", 300)
    table = resolve_dataset_stay_table("mimic-iv", dataset_version="2.2")
    assert table is not None and table.path == expected.resolve()


def test_discovery_searches_later_roots_for_the_requested_version(
    tmp_path: Path, isolated_data_roots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # First root (WEAVEHR_YAIB_DATA_ROOT) only has 3.1; the second has 2.2.
    _icustays(isolated_data_roots / "physionet.org/files/mimiciv/3.1/icu/icustays.csv.gz", 300)
    second = tmp_path / "ricu"
    expected = _icustays(second / "physionet.org/files/mimiciv/2.2/icu/icustays.csv.gz", 100)
    monkeypatch.setenv("RICU_DATA_PATH", str(second))

    table = resolve_dataset_stay_table("mimic-iv", dataset_version="2.2")
    assert table is not None and table.path == expected.resolve()

    # Neither root has 3.0: the error lists the candidates of both roots.
    with pytest.raises(ValueError, match="mimiciv/2.2.*mimiciv/3.1|mimiciv/3.1.*mimiciv/2.2"):
        resolve_dataset_stay_table("mimic-iv", dataset_version="3.0")
