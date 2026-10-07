"""Locate inputs inside a WeavEHR project directory.

A ``weavehr.WeavEHRProject`` has the layout::

    <project>/
      configs/
      workspace/<step>/...            # step output written while running
      datasets/<step>/data/...        # the same output collected as a MEDS dataset

Step directories are the lowercased step config ``name`` (``Extraction`` and
``Concept`` in the WeavEHR examples). Extraction events are written to
``<step>/<dataset>/<version>/<table>/<EVENT>.parquet`` and concepts to
``concept/<concept>/<version>/<dataset>.parquet``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .io import scan_weavehr_aumc_stays, scan_weavehr_hirid_stays, scan_weavehr_sic_stays

DEFAULT_EXTRACTION_STEP = "extraction"


def resolve_weavehr_workspace(path: str | Path) -> Path:
    """Resolve the WeavEHR ``workspace`` directory containing the step outputs.

    Accepted inputs are a WeavEHR project root (containing ``workspace`` plus
    ``datasets`` and/or ``configs``), the workspace itself, the concept
    directory, or an arbitrary output directory. For an arbitrary directory we
    use that directory as the workspace root.
    """
    root = Path(path).expanduser().resolve()
    if root.name == "concept":
        return root.parent
    if (root / "workspace").is_dir() and (
        (root / "workspace" / "concept").exists()
        or (root / "datasets").is_dir()
        or (root / "configs").is_dir()
    ):
        return root / "workspace"
    return root


def yaib_root_from_output(path: str | Path) -> Path:
    """Return/create ``yaib`` next to the WeavEHR step directories in the workspace."""
    workspace = resolve_weavehr_workspace(path)
    out = workspace / "yaib"
    out.mkdir(parents=True, exist_ok=True)
    return out


def concept_root_from_output(path: str | Path) -> Path:
    """Return the concept root implied by a WeavEHR project/workspace path."""
    root = Path(path).expanduser().resolve()
    if root.name == "concept":
        return root
    workspace = resolve_weavehr_workspace(root)
    return workspace / "concept"


def step_output_dirs(
    workspace: str | Path, dataset: str, *, step: str = DEFAULT_EXTRACTION_STEP
) -> list[Path]:
    """Return candidate directories holding one dataset's output of a WeavEHR step.

    WeavEHR writes step output to ``workspace/<step>/<dataset>`` and collects a
    copy into ``datasets/<step>/data/<dataset>``; both are searched in that order.
    """
    workspace = Path(workspace)
    return [
        workspace / step / dataset,
        workspace.parent / "datasets" / step / "data" / dataset,
    ]


def find_step_output_file(
    workspace: str | Path,
    dataset: str,
    filename: str,
    *,
    step: str = DEFAULT_EXTRACTION_STEP,
    version: str | None = None,
) -> Path:
    """Find exactly one ``filename`` below a dataset's WeavEHR step output.

    The first candidate directory from :func:`step_output_dirs` containing the
    file wins. ``version`` restricts the search to that dataset-version
    directory. Several matches in one directory (e.g. multiple extracted
    dataset versions) are ambiguous and raise.
    """
    searched = step_output_dirs(workspace, dataset, step=step)
    if version is not None:
        searched = [root / version for root in searched]
    for root in searched:
        matches = sorted(root.rglob(filename)) if root.is_dir() else []
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise FileNotFoundError(
                f"Expected exactly one {dataset} {filename} below {root}, found {len(matches)}"
            )
    locations = ", ".join(str(p) for p in searched)
    raise FileNotFoundError(f"Could not find {dataset} {filename} below any of: {locations}")


def weavehr_aumc_stays(
    workspace: str | Path, *, step: str = DEFAULT_EXTRACTION_STEP, version: str | None = None
) -> pl.LazyFrame:
    """Build AUMC ICU stays from the WeavEHR ``VISIT_START``/``VISIT_END`` events."""
    return scan_weavehr_aumc_stays(
        find_step_output_file(workspace, "aumc", "VISIT_START.parquet", step=step, version=version),
        find_step_output_file(workspace, "aumc", "VISIT_END.parquet", step=step, version=version),
    )


def weavehr_hirid_stays(
    workspace: str | Path, *, step: str = DEFAULT_EXTRACTION_STEP, version: str | None = None
) -> pl.LazyFrame:
    """Build HiRID ICU stays from the WeavEHR ``ICU_ADMISSION``/``OBSERVATION`` events."""
    return scan_weavehr_hirid_stays(
        find_step_output_file(
            workspace, "hirid", "ICU_ADMISSION.parquet", step=step, version=version
        ),
        find_step_output_file(
            workspace, "hirid", "OBSERVATION.parquet", step=step, version=version
        ),
    )


def weavehr_sic_stays(
    workspace: str | Path, *, step: str = DEFAULT_EXTRACTION_STEP, version: str | None = None
) -> pl.LazyFrame:
    """Build SIC ICU stays (one per ``case_id``) from the WeavEHR ``cases`` events."""
    return scan_weavehr_sic_stays(
        find_step_output_file(
            workspace, "sic", "ICU_ADMISSION.parquet", step=step, version=version
        ),
        find_step_output_file(workspace, "sic", "OBSERVATION.parquet", step=step, version=version),
    )
