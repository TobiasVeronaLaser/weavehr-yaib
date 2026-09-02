# openicu-yaib

`openicu-yaib` converts OpenICU concept outputs to a YAIB-compatible wide-table representation. For datasets that also have a configured RICU source, it can additionally generate comparable OpenICU and RICU outputs and produce diagnostic comparison reports.

The repository does **not** run YAIB or YAIB-cohorts itself. Its role is the OpenICU → YAIB-wide conversion and the technical comparison of OpenICU outputs against RICU where a matching RICU source is available.

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

Every notebook performs the full OpenICU export over **all concept parquet files present for that dataset**. The resulting schema contains one column per discovered OpenICU concept. The wide representation used here is numeric, so concepts without numeric values remain present as all-null numeric columns rather than being silently omitted. A CSV manifest records every concept parquet used.

This conversion should not be interpreted as meaning that every OpenICU concept is used by YAIB. OpenICU can also produce concepts that are outside the scope of the YAIB-wide variables used by this validation workflow.

For datasets with a RICU source, the notebook additionally:

1. runs the matching R wrapper from `scripts/datasets/`;
2. creates the OpenICU YAIB/RICU-compatible 168-hour wide table;
3. normalizes the RICU wide reference to the same ICU windows;
4. compares the OpenICU and RICU outputs over the configured first-168-hour window and writes separate diagnostic reports for overlap, coverage, missingness, value differences, and reproduction accuracy.

The first 168 hours (7 days) are the **current comparison window used by this project**. This repository does not claim a clinical, benchmark-specific, or technical rationale for why exactly seven days were chosen, and the 168-hour window is not an inherent limitation of the general OpenICU → wide-table conversion.

`mimic-iv-demo` and `nwicu` intentionally have no R file and no RICU comparison because they have no corresponding native source in the configured RICU source set.

### Interpreting the validation reports

The generated reports are **separate diagnostics**, not components of one blended validation score.

Examples include:

- key and stay overlap;
- concept-wise non-null coverage;
- missingness on common `(stay_id, time)` keys;
- absolute and relative numerical value differences where both sides contain a value;
- stay- and row-level reproduction statistics.

In particular, `value_diff` is only one diagnostic report and should not be interpreted as the overall validation result.

The comparison code itself does **not** implement or enforce a canonical `<1% per concept` acceptance rule. If a project-level `<1% per concept` criterion is used during manual validation, that is an external working convention and its exact metric should be stated explicitly rather than inferred from the available reports.

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

### AUMC stay mapping

AUMC requires explicit admission provenance because a patient can have multiple
ICU admissions. The raw AmsterdamUMCdb stay mapping uses `patientid` as
`subject_id` and `admissionid` as `stay_id`.

When an AUMC OpenICU workspace is used without an explicit stay-table override,
the workflow automatically builds normalized ICU windows from the OpenICU
`VISIT_START.parquet` and `VISIT_END.parquet` extraction outputs. Concept
events that contain `visit_occurrence_id` are mapped directly by
`(subject_id, visit_occurrence_id)` rather than being joined to every stay of
the same patient. This preserves admission provenance and prevents events from
one admission being assigned to another admission of the same patient.

For the RICU comparison, AUMC reference exports may use `measuredat` as their
time column; the comparison workflow normalizes that column to the same
hour-based representation used by the other supported RICU references.

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

Using `max_hours=None` performs the general wide-table export without imposing the 168-hour validation window.

For the RICU-backed comparison workflow, the dataset notebooks call `build_and_write_yaib_wide_for_dataset(...)` and `compare_openicu_wide_to_ricu_for_dataset(...)`. The reports produced by `openicu_yaib.compare` are intended as complementary diagnostics and should be interpreted individually.

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
  compare.py                  # overlap/difference/reproduction diagnostics
  workflow.py                 # notebook-friendly bounded validation workflow
```
