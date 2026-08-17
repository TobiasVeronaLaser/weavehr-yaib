# openicu-yaib

`openicu-yaib` converts OpenICU concept outputs to YAIB-style wide tables. The repository also contains optional workflows for validating compatible datasets against RICU.

## Dataset workflows

There is exactly one notebook per requested dataset in `example/datasets/`:

- `aumc`
- `eicu-crd`
- `eicu-demo`
- `hirid`
- `mimic-iii`
- `mimic-iii-demo`
- `mimic-iv`
- `mimic-iv-demo`
- `nwicu`
- `sic`

The duplicated `mimic-iii` requirement is represented as `mimic-iii` and `mimic-iii-demo`, matching the existing multi-dataset feature branch and the RICU sources `mimic` / `mimic_demo`.

Every notebook performs the full OpenICU export over **all concept parquet files present for that dataset**. The resulting schema contains one column per discovered OpenICU concept. YAIB's dynamic representation is numeric, so concepts without numeric values remain present as all-null numeric columns rather than being silently omitted. A CSV manifest records every concept parquet used.

For datasets with a RICU source, the current validation workflow can additionally:

1. runs the one matching R wrapper from `scripts/datasets/`;
2. creates the OpenICU YAIB/RICU-compatible 168-hour wide table;
3. normalizes the RICU wide reference to the same ICU windows;
4. compares **only the first 7 days (`0..168` hours)** and writes overlap, coverage, missingness, value-difference and reproduction-accuracy inputs/reports.

`mimic-iv-demo` and `nwicu` intentionally have no R file and no RICU comparison because they have no corresponding native source in the configured RICU source set.

RICU source mapping:

| OpenICU dataset | RICU source |
|---|---|
| `aumc` | `aumc` |
| `eicu-crd` | `eicu` |
| `eicu-demo` | `eicu_demo` |
| `hirid` | `hirid` |
| `mimic-iii` | `mimic` |
| `mimic-iii-demo` | `mimic_demo` |
| `mimic-iv` | `miiv` |
| `mimic-iv-demo` | — |
| `nwicu` | — |
| `sic` | `sic` |

## Output layout

Pass `OPENICU_OUTPUT` in a dataset notebook as either:

- the OpenICU project root (`.../project`),
- the OpenICU workspace (`.../project/workspace`),
- the concept directory (`.../project/workspace/concept`), or
- another output directory.

For an OpenICU project root the package detects `workspace` automatically. The YAIB step is placed next to `extraction`, `concept`, `sharding`, and `persisting`:

```text
project/
  workspace/
    extraction/
    concept/
    sharding/
    persisting/
    yaib/
      eicu-crd/
        openicu_all_concepts_wide.parquet
        openicu_all_concepts_wide_concepts.csv
        openicu_dyn_168h.parquet
        ricu_dynamic_vars_eicu.parquet
        ricu_stay_windows_eicu.parquet
        reports/
          168h/
            ricu_reference_normalized.parquet
            ...csv
```

For a separate output directory, the same `yaib/<dataset>/...` subtree is created there. By default `concept/` is expected beside `yaib/`; pass `concept_root=` explicitly if the concepts live elsewhere.

## Install

```bash
python -m pip install -e .
```

Development:

```bash
python -m pip install -e ".[dev]"
pytest -q
```

## Main Python API

```python
from openicu_yaib import write_all_concepts_wide

result = write_all_concepts_wide(
    dataset="eicu-crd",
    openicu_output="/path/to/project/workspace",
    max_hours=None,
)
```

Optional RICU validation workflows can create a bounded 7-day subset with `build_and_write_yaib_wide_for_dataset(...)` and compare it using `compare_openicu_wide_to_ricu_for_dataset(...)`. These workflows are separate from the all-concepts YAIB export.

## Repository layout

```text
configs/                     # RICU/YAIB concept + unit mappings
example/datasets/            # exactly one .ipynb per dataset
scripts/datasets/            # one .R wrapper per RICU-backed dataset
scripts/                     # shared R export implementation
src/openicu_yaib/
  all_concepts.py             # all-OpenICU-concept wide export + output placement
  datasets.py                 # canonical dataset/RICU registry
  stays.py                    # dataset-specific stay table discovery/mapping
  transform.py                # YAIB/RICU-compatible dynamic transform
  compare.py                  # overlap/difference/reproduction metrics
  workflow.py                 # notebook-friendly 7-day validation workflow
```
