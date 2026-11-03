"""Compare YAIB-cohorts task outputs extracted with ricu and with the WeavEHR backend.

YAIB-cohorts writes each task to ``<out_dir>/<task>/<src>/`` with ``outc.parquet`` (labels),
``dyn.parquet`` (hourly variables), ``sta.parquet`` (static variables) and ``attrition.csv``.
This module compares two such outputs, typically ricu (e.g. ``miiv``) against WeavEHR
(e.g. ``mimic-iv``). The reports hold counts and agreement fractions only, no stay IDs or values.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

TASKS = ("mortality24", "aki", "sepsis", "kidney_function", "los")


@dataclass(frozen=True)
class CohortComparison:
    """Comparison of one task between ricu and WeavEHR."""

    attrition: pl.DataFrame
    cohort: pl.DataFrame
    labels: pl.DataFrame
    variables: pl.DataFrame


def read_task(task_dir: str | Path) -> dict[str, pl.DataFrame]:
    """Read the outputs of one YAIB-cohorts task for one source."""
    task_dir = Path(task_dir)
    res = {}
    for name in ("outc", "dyn", "sta"):
        df = pl.read_parquet(task_dir / f"{name}.parquet")
        # ricu writes stay_id and time as doubles, WeavEHR as integers
        res[name] = df.with_columns(
            pl.col(c).cast(pl.Int64) for c in ("stay_id", "time") if c in df.columns
        )
    res["attrition"] = pl.read_csv(task_dir / "attrition.csv").select(
        "desc", "n_excluded", "n_left"
    )
    return res


def _label_keys(outc: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    """Keys of the label rows: stay and hour, or the row within the stay for hourly labels
    without time."""
    if "time" in outc.columns:
        return outc, ["stay_id", "time"]
    if outc["stay_id"].is_duplicated().any():
        return outc.with_columns(pl.int_range(pl.len()).over("stay_id").alias("row")), [
            "stay_id",
            "row",
        ]
    return outc, ["stay_id"]


def _equal(a: pl.Expr, b: pl.Expr, numeric: bool, rtol: float, atol: float) -> pl.Expr:
    if numeric:
        return (a - b).abs() <= atol + rtol * b.abs()
    return a == b


def compare_labels(
    ricu: pl.DataFrame, weavehr: pl.DataFrame, rtol: float = 1e-3, atol: float = 1e-6
) -> pl.DataFrame:
    """Agreement of the labels on the label rows present in both outputs.

    Binary labels report the agreement and the number of stays with a positive label;
    other labels the fraction of equal values and their correlation.
    """
    ricu, keys = _label_keys(ricu)
    weavehr, _ = _label_keys(weavehr)
    both = ricu.join(weavehr, on=keys, how="inner", suffix="_weavehr")
    a, b = pl.col("label"), pl.col("label_weavehr")
    binary = all(
        set(df["label"].drop_nulls().unique().to_list()) <= {0, 1} for df in (ricu, weavehr)
    )
    stats = {
        "keys": "/".join(keys),
        "n_ricu": ricu.height,
        "n_weavehr": weavehr.height,
        "n_common": both.height,
    }
    if binary:
        common = set(ricu["stay_id"]) & set(weavehr["stay_id"])
        pos = [
            set(
                df.filter((pl.col("label") == 1) & pl.col("stay_id").is_in(list(common)))["stay_id"]
            )
            for df in (ricu, weavehr)
        ]
        stats |= {
            "agreement": both.select((a == b).mean()).item(),
            "positive_stays_ricu": len(pos[0]),
            "positive_stays_weavehr": len(pos[1]),
            "positive_stays_both": len(pos[0] & pos[1]),
        }
    else:
        stats |= {
            "agreement": both.select(_equal(a, b, True, rtol, atol).mean()).item(),
            "correlation": both.select(pl.corr(a, b)).item(),
        }
    return pl.DataFrame([stats])


def compare_variables(
    ricu: pl.DataFrame,
    weavehr: pl.DataFrame,
    keys: Sequence[str],
    table: str,
    rtol: float = 1e-3,
    atol: float = 1e-6,
) -> pl.DataFrame:
    """Per variable, on the keys present in both outputs: values in each, in both, the fraction of
    equal values where both have one and the coverage of WeavEHR relative to ricu."""
    both = ricu.join(weavehr, on=list(keys), how="inner", suffix="_weavehr")
    rows = []
    for var in [c for c in ricu.columns if c not in keys and c in weavehr.columns]:
        a, b = pl.col(var), pl.col(f"{var}_weavehr")
        numeric = both.schema[var].is_numeric()
        present = a.is_not_null() & b.is_not_null()
        n_ricu, n_weavehr, n_both, equal = both.select(
            a.is_not_null().sum().alias("n_ricu"),
            b.is_not_null().sum().alias("n_weavehr"),
            present.sum().alias("n_both"),
            _equal(a, b, numeric, rtol, atol).filter(present).mean().alias("equal"),
        ).row(0)
        rows.append(
            {
                "table": table,
                "variable": var,
                "n_ricu": n_ricu,
                "n_weavehr": n_weavehr,
                "n_both": n_both,
                "equal": equal,
                "coverage": n_weavehr / n_ricu if n_ricu else None,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "table": pl.String,
            "variable": pl.String,
            "n_ricu": pl.Int64,
            "n_weavehr": pl.Int64,
            "n_both": pl.Int64,
            "equal": pl.Float64,
            "coverage": pl.Float64,
        },
    )


def compare_task(
    ricu_dir: str | Path, weavehr_dir: str | Path, rtol: float = 1e-3, atol: float = 1e-6
) -> CohortComparison:
    """Compare one task extracted with ricu (``ricu_dir``) and with WeavEHR (``weavehr_dir``)."""
    r, w = read_task(ricu_dir), read_task(weavehr_dir)
    attrition = r["attrition"].join(
        w["attrition"],
        on="desc",
        how="full",
        suffix="_weavehr",
        coalesce=True,
        maintain_order="left_right",
    )
    attrition = attrition.rename({"n_excluded": "n_excluded_ricu", "n_left": "n_left_ricu"})
    rs, ws = set(r["sta"]["stay_id"]), set(w["sta"]["stay_id"])
    cohort = pl.DataFrame(
        [
            {
                "n_ricu": len(rs),
                "n_weavehr": len(ws),
                "n_both": len(rs & ws),
                "n_only_ricu": len(rs - ws),
                "n_only_weavehr": len(ws - rs),
            }
        ]
    )
    variables = pl.concat(
        [
            compare_variables(r["sta"], w["sta"], ["stay_id"], "sta", rtol, atol),
            compare_variables(r["dyn"], w["dyn"], ["stay_id", "time"], "dyn", rtol, atol),
        ]
    )
    return CohortComparison(
        attrition, cohort, compare_labels(r["outc"], w["outc"], rtol, atol), variables
    )


def compare_outputs(
    ricu_root: str | Path,
    weavehr_root: str | Path,
    ricu_src: str,
    weavehr_src: str,
    output_dir: str | Path,
    tasks: Sequence[str] | None = None,
    rtol: float = 1e-3,
) -> pl.DataFrame:
    """Compare all tasks present for both sources and write the reports to ``output_dir/<task>/``.

    Returns a summary with one row per task, also written to ``output_dir/summary.csv``.
    """
    ricu_root, weavehr_root, output_dir = Path(ricu_root), Path(weavehr_root), Path(output_dir)
    tasks = [
        t
        for t in (tasks or TASKS)
        if (ricu_root / t / ricu_src).is_dir() and (weavehr_root / t / weavehr_src).is_dir()
    ]
    summary = []
    for task in tasks:
        res = compare_task(ricu_root / task / ricu_src, weavehr_root / task / weavehr_src, rtol)
        task_dir = output_dir / task
        task_dir.mkdir(parents=True, exist_ok=True)
        for name in ("attrition", "cohort", "labels", "variables"):
            getattr(res, name).write_csv(task_dir / f"{name}.csv")
        labels = res.labels.row(0, named=True)
        differing = res.variables.filter((pl.col("equal") < 1) | (pl.col("coverage") != 1))[
            "variable"
        ].to_list()
        summary.append(
            {
                "task": task,
                **res.cohort.row(0, named=True),
                "label_agreement": labels["agreement"],
                "variables_differing": ", ".join(differing),
            }
        )
    res = pl.DataFrame(summary)
    output_dir.mkdir(parents=True, exist_ok=True)
    res.write_csv(output_dir / "summary.csv")
    return res


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Compare YAIB-cohorts outputs extracted with ricu and with WeavEHR."
    )
    parser.add_argument("--ricu-dir", required=True, help="YAIB-cohorts out_dir of the ricu run")
    parser.add_argument(
        "--weavehr-dir", required=True, help="YAIB-cohorts out_dir of the WeavEHR run"
    )
    parser.add_argument("--ricu-src", required=True, help="ricu source, e.g. miiv")
    parser.add_argument("--weavehr-src", required=True, help="WeavEHR dataset, e.g. mimic-iv")
    parser.add_argument("--output-dir", required=True, help="directory for the reports")
    parser.add_argument("--tasks", nargs="*", default=None, help=f"default: {' '.join(TASKS)}")
    parser.add_argument("--rtol", type=float, default=1e-3, help="relative tolerance of values")
    args = parser.parse_args(argv)
    summary = compare_outputs(
        args.ricu_dir,
        args.weavehr_dir,
        args.ricu_src,
        args.weavehr_src,
        args.output_dir,
        args.tasks,
        args.rtol,
    )
    with pl.Config(tbl_rows=-1, tbl_cols=-1, fmt_str_lengths=200, tbl_width_chars=200):
        print(summary)


if __name__ == "__main__":
    main()
