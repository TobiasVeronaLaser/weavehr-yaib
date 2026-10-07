# weavehr-yaib

`weavehr-yaib` converts WeavEHR concept outputs to a YAIB-compatible wide-table representation. For datasets that also have a configured RICU source, it can additionally generate comparable WeavEHR and RICU outputs and produce diagnostic comparison reports.

The repository does **not** run YAIB or YAIB-cohorts itself. Its role is the WeavEHR → YAIB-wide conversion and the technical comparison of WeavEHR outputs against RICU where a matching RICU source is available.

> This project was previously named `openicu-yaib` (Python package `openicu_yaib`), after the pipeline's former name OpenICU. The notebooks in `example/notebooks/archive/` predate the rename and are kept as historical material; see their [README](example/notebooks/archive/README.md).

## Relationship to WeavEHR

`weavehr-yaib` does not import the [WeavEHR](https://github.com/aidh-ms/WeavEHR) Python package and does not depend on it. It reads the parquet files a WeavEHR project writes to disk. Produce these with WeavEHR first (`WeavEHRProject`, `ExtractionStep`, `ConceptStep`; see the WeavEHR documentation), then point the notebooks of this repository at the resulting project directory.

The inputs used here are:

- concept outputs: `workspace/concept/<concept>/<version>/<dataset>.parquet` with the MEDS columns `subject_id`, `time` and `numeric_value`;
- for AUMC and HiRID stay windows, extraction events: `workspace/extraction/<dataset>/<version>/<table>/<EVENT>.parquet`, or the collected copy below `datasets/extraction/data/<dataset>/...`.

`extraction` and `concept` are the lowercased step `name`s used in the WeavEHR example step configs (`Extraction`, `Concept`).

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

> **`mimic-iii` and `mimic-iii-demo` require custom WeavEHR dataset configs.** Current WeavEHR does not bundle dataset configs for them (`DatasetSpec.weavehr_bundled` is `False`), so WeavEHR produces no concept output for these datasets out of the box. Their notebooks and RICU wrappers only work once you have run WeavEHR with your own extraction tables and concept mappings for these datasets. All other listed datasets have configs bundled with WeavEHR.

Every notebook performs the full WeavEHR export over **all concept parquet files present for that dataset**. The resulting schema contains one column per discovered WeavEHR concept. The wide representation used here is numeric, so concepts without numeric values remain present as all-null numeric columns rather than being silently omitted. A CSV manifest records every concept parquet used.

This conversion should not be interpreted as meaning that every WeavEHR concept is used by YAIB. WeavEHR can also produce concepts that are outside the scope of the YAIB-wide variables used by this validation workflow.

For datasets with a RICU source, the notebook additionally:

1. runs the matching R wrapper from `scripts/datasets/`;
2. creates the WeavEHR YAIB/RICU-compatible 168-hour wide table;
3. normalizes the RICU wide reference to the same ICU windows;
4. compares the WeavEHR and RICU outputs over the configured first-168-hour window and writes separate diagnostic reports for overlap, coverage, missingness, value differences, and reproduction accuracy.

The first 168 hours (7 days) are the **current comparison window used by this project**. This repository does not claim a clinical, benchmark-specific, or technical rationale for why exactly seven days were chosen, and the 168-hour window is not an inherent limitation of the general WeavEHR → wide-table conversion.

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

| WeavEHR dataset | RICU source |
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

## Dataset versions and comparison scope

A dataset name does not identify a dataset version. RICU's `aumc` source reads
AmsterdamUMCdb 1.0.2 in its native tables, while WeavEHR reads AUMC 1.5.0
through the AMSTEL OMOP export; RICU's `miiv` targets MIMIC-IV 2.2, while
WeavEHR also supports 3.1. Every comparison therefore records both versions.

**WeavEHR version**, resolved in this order, never guessed:

1. explicit `dataset_version=` (version source `explicit`);
2. the `dataset_version` column of the concept outputs (`concept_column`);
3. the single version directory of the extraction output (`extraction_dirs`).

Several versions without an explicit choice raise an error. If several
versions were extracted but the concept outputs have no `dataset_version`
column, the rows cannot be attributed to a version (WeavEHR writes all
versions of a dataset into one `<dataset>.parquet`) and the run fails. Add
`dataset_version: col("version")` to the concept step `extension_columns` for
such projects. The wide export records the resolved version in
`<output>.provenance.json`. Every export that writes this file also stores a
random `provenance_id` in the parquet metadata; a provenance file whose ID does
not match its parquet (e.g. the parquet was overwritten by another writer) is
rejected as stale, and writers without provenance remove an existing one. A
provenance file built for another dataset is rejected as well.

The same rules apply to the config/CLI path: set `concepts.dataset_version` in
the config or pass `--dataset-version`.

**Raw stay tables** must match the WeavEHR dataset version. An explicit table
(`icustays_csv`/`stays_path`, `WEAVEHR_YAIB_ICUSTAYS_CSV`,
`WEAVEHR_YAIB_<DATASET>_STAYS`) whose path names another version is rejected.
A path names a version through its dataset folder, in the PhysioNet wget
layout (`.../mimiciv/3.1/...`) or ZIP layout (`.../mimic-iv-3.1/...`,
`.../eicu-collaborative-research-database-2.0/...`); version-like directories
unrelated to the dataset (`/srv/1.0/...`) are ignored. Discovery searches all
data roots for a table whose path names the WeavEHR version and fails when
none or several qualify; the selected table's path, version and selection mode
are recorded in the provenance (`stay_table_*`).

**Reference version**, in this order:

| Version source | Meaning | Verified |
|---|---|---|
| `explicit` | `reference_version=` argument | yes |
| `provenance_file` | `RICU_SOURCE_VERSION` declared when running the R export | yes |
| `ricu_config` | version in RICU's source URL (MIMIC-IV 2.2, MIMIC-III 1.4, eICU 2.0, eICU demo 2.0.1, HiRID 1.1.1, SICdb 1.0.6) | no, assumed |
| `manual_default` | maintained default where RICU has none (AUMC 1.0.2) | no, assumed |
| `unknown` | none of the above | no |

The R export writes `ricu_dynamic_vars_<src>.provenance.json` with the RICU
package version and source URL; set `RICU_SOURCE_VERSION` to declare the
version of the data in `RICU_DATA_PATH`.

**Scope and validation level.** The `provenance` report states
`weavehr_dataset_version`, `reference_dataset_version`, how each was
determined, `same_version` (null if either version is unknown),
`comparison_scope` and `validation_level`:

| `validation_level` | When | Metrics cover |
|---|---|---|
| `full_same_version` | both versions verified and identical, stays in a common identifier space | the full comparison |
| `shared_subset_cross_version` | both versions verified, different | shared stays × shared concepts |
| `shared_subset_unverified_version` | a version is assumed or unknown | shared stays × shared concepts |
| `shared_subset_stay_crosswalk` | both versions verified and identical, stays linked by a crosswalk | mapped shared stays × shared concepts |
| `not_comparable` | no shared stays or concepts | nothing |

Only `full_same_version` is full validation. A clean shared-subset result
shows reproduction of the shared part, not semantic equivalence of the
datasets. Outside the full scope, WeavEHR-only and reference-only stays and
concepts are not scored as errors: `scope_overlap` counts them with a
relationship (`equal`, `weavehr_superset`, `reference_superset`,
`partial_overlap`, `not_directly_comparable`) and `scope_differences` lists
them. `reproduction_accuracy` repeats the versions, scope and validation level
next to the aggregate numbers. Reports are written to
`reports/<horizon>/weavehr-<version>__ricu-<source>-<version>/`.

### Stay identifier spaces

Stays are matched by ID only when both sides use the same declared identifier
space, or through a stay crosswalk. Equal numbers in different spaces are never
treated as the same stay.

| Side | Stay IDs | Identifier space |
|---|---|---|
| RICU | ICU stay ID of the source (`id_cfg`) | e.g. `mimic-iv:icustays.stay_id`, `aumcdb:admissions.admissionid` |
| WeavEHR, raw stay table | the stay table's ID (`stays.py`) | e.g. `mimic-iv:icustays.stay_id`; none for AUMC and SIC (rejected, see below) |
| WeavEHR, AUMC visit events | OMOP `visit_occurrence_id` | `omop:visit_occurrence.visit_occurrence_id` |
| WeavEHR, HiRID events | `patientid` | `hirid:general.patientid` |
| WeavEHR, SIC cases events | `case_id` (SICdb `CaseID`) | `sicdb:cases.caseid` |

The WeavEHR space is recorded in the wide export's provenance file. The
`provenance` report contains `weavehr_stay_id_space`, `reference_stay_id_space`,
`stay_comparison_basis`, `stay_comparison_confidence` and
`stay_id_version_assumption` (`same_verified_version`,
`unverified_cross_version_stability`, `crosswalk`, `not_applicable`):

- `direct_identifier_match`: same declared space; confidence `high` for
  verified identical dataset versions, else `medium`. Identifier spaces are
  named per dataset, not per version: whether stay IDs are preserved across
  versions (e.g. MIMIC-IV 2.2 → 3.1) is not documented in the available
  sources, so such matches are reported with
  `stay_id_version_assumption = unverified_cross_version_stability`.
- `crosswalk`: `stay_crosswalk=` (one-to-one `reference_stay_id`,
  `weavehr_stay_id`) translates reference stays into the WeavEHR space before
  any matching. Reference stays without an entry are listed as
  `reference_without_crosswalk`. Confidence `medium`; never full validation
  (`shared_subset_stay_crosswalk` for verified identical versions).
- `side_by_side_only`: different or unknown spaces. No stay-keyed report
  (windows, keys, reproduction metrics) is computed and `validation_level` is
  `not_comparable`. Provenance, the concept overlap and both stay ID sets
  (`scope_differences`, sides `weavehr` and `reference`) are still reported.

AUMC is `side_by_side_only` until a verified `admissionid` ↔
`visit_occurrence_id` crosswalk is supplied.

## Item-level review

`write_item_review_for_dataset(...)` writes `item_review.csv` (one row per
concept and item) and `item_review_summary.csv` (one row per concept) to
`item_review/weavehr-<version>__ricu-<source>-<version>/`, for review by a
medical expert. Each row carries both dataset versions, version sources and
representations, the item status (`shared`, `weavehr_only`, `reference_only`,
`not_directly_comparable`), `comparison_basis` and `comparison_confidence`,
plus empty `review_verdict`, `review_comment` and `reviewer` columns.
Suggested verdicts: `accept` (e.g. accept additional WeavEHR coverage),
`reject`, `questionable_reference`, `incorrect_reference`, `needs_discussion`.
Reviewer entries are kept when the review is regenerated.

WeavEHR items are the source codes observed in the concept outputs; this
requires `source_code: col("code")` in the concept step `extension_columns`
(the run fails otherwise). Reference items are those RICU's `concept-dict.json`
configures for the source (`item_set_basis` =
`weavehr_observed_vs_reference_configured`). Item statuses therefore compare
WeavEHR data occurrence with RICU mapping coverage. Each row states its evidence
separately:

| Column | Meaning |
|---|---|
| `weavehr_observed` | item occurs in the WeavEHR concept data (`weavehr_n_rows`) |
| `weavehr_configured` | always empty: WeavEHR mapping configs are not evaluated per item |
| `reference_configured` | item is in RICU's concept-dict |
| `reference_observed` | item occurs in RICU data (`reference_n_rows`); empty when unknown |
| `evidence` | the above in words, e.g. "configured in RICU concept-dict; RICU data occurrence unknown" |

Flags about the other side are only filled when both sides share the
identifier space. RICU exports carry no item provenance, so
`reference_observed` stays empty unless `reference_observed_items=`
(`ricu_concept`, `item_id`, optional `n_rows`) is supplied. The summary counts
`n_weavehr_observed_items`, `n_weavehr_observed_rows`,
`n_reference_configured_items`, `n_reference_observed_items` and
`n_reference_configured_not_observed` (empty when unknown).

Items are only matched on a declared common identifier space or a crosswalk:

| `comparison_basis` | When | `comparison_confidence` |
|---|---|---|
| `direct_identifier_match` | both sides use the same declared space; currently only WeavEHR `mimic-iv` vs RICU `miiv` (MIMIC-IV itemids) | `high` for verified identical versions, else `medium` |
| `crosswalk` | a `crosswalk=` table (`reference_item_id`, `weavehr_item_id`) is given | `medium` |
| `side_by_side_only` | anything else, including AUMC (OMOP `concept_id` vs native itemid) without a crosswalk and all MIMIC-III pairs | `not_comparable` |

Side-by-side items keep their identifiers and labels but are never matched,
including by label. An item only present in WeavEHR is not an error by itself
(it may be coverage of a newer dataset version); a reference item may itself
be marked questionable or incorrect.

## Output layout

Pass `WEAVEHR_OUTPUT` in a dataset notebook as either:

- the WeavEHR project root (`.../project`, containing `workspace/`, `datasets/` and `configs/`),
- the WeavEHR workspace (`.../project/workspace`),
- the concept directory (`.../project/workspace/concept`), or
- another output directory.

For a WeavEHR project root the package detects `workspace` automatically. The YAIB output is placed next to the WeavEHR step directories:

```text
project/
  configs/
  datasets/
    extraction/data/...
    concept/data/...
  workspace/
    extraction/
    concept/
    yaib/
      eicu-crd/
        weavehr_all_concepts_wide.parquet
        weavehr_all_concepts_wide_concepts.csv
        weavehr_dyn_168h.parquet
        ricu_dynamic_vars_eicu.parquet
        ricu_stay_windows_eicu.parquet
        weavehr_dyn_168h.provenance.json
        ricu_dynamic_vars_eicu.provenance.json
        reports/
          168h/
            weavehr-2.0__ricu-eicu-2.0/
              provenance.csv
              scope_overlap.csv
              scope_differences.csv
              ricu_reference_normalized.parquet
              ...csv
        item_review/
          weavehr-2.0__ricu-eicu-2.0/
            item_review.csv
            item_review_summary.csv
```

For a separate output directory, the same `yaib/<dataset>/...` subtree is created there. By default `concept/` is expected beside `yaib/`; pass `concept_root=` explicitly if the concepts live elsewhere.

### AUMC stay mapping

AUMC requires explicit admission provenance because a patient can have multiple
ICU admissions. The raw AmsterdamUMCdb stay mapping uses `patientid` as
`subject_id` and `admissionid` as `stay_id`. WeavEHR concept events instead
carry the AMSTEL OMOP `person_id` and `visit_occurrence_id`. No available
source documents that AMSTEL preserves the native IDs, so a native admissions
table is rejected with an error when combined with WeavEHR concepts (explicit
`icustays_csv`/`stays_path` or automatic discovery) instead of being joined by
equal numbers.

The same applies to SIC: WeavEHR uses the SICdb `PatientID` as `subject_id`
(`CaseID` only as the `case_id` extension) on a per-patient synthetic time
axis, while the raw `cases` table spec uses `CaseID` with case-relative
offsets, so a raw SIC stay table is rejected as well.

### SIC stays

Without a stay table, SIC stays are built from the WeavEHR `cases` extraction
events, one stay per case:

- `stay_id` is the case's `case_id` (SICdb `CaseID`); `subject_id` stays the
  `PatientID`, so several cases of one patient remain separate stays.
- WeavEHR places every SICdb event of a patient on one synthetic axis:
  Jan 1 of the patient's first admission year + `OffsetAfterFirstAdmission` +
  `Offset` (seconds). The stay starts at the case's `ICU_ADMISSION` event
  (`Offset` 0 of the case) and ends at the case's latest `OBSERVATION`
  (`data_float_h`) event, as WeavEHR does not extract `TimeOfStay`. Stay-relative
  hours therefore equal `Offset / 3600`.
- Concept events are assigned to their stay by `case_id`, which must be kept in
  the WeavEHR concept step:

  ```yaml
  mapping_configs:
    - name: sic
      version: "1.0.6"
      extension_columns:
        case_id: col("case_id")
  ```

  Without it the run fails; `PatientID` is never used as a stay ID.
- The wide export records `stay_id_space = sicdb:cases.caseid`, the same space
  as RICU's SIC `CaseID`, so SIC is compared to RICU directly by stay ID.

RICU's SIC stay window starts at `ICUOffset` and ends at `TimeOfStay`; neither
is in the WeavEHR output. Where `ICUOffset` is not 0, RICU's hour 0 lies that
many seconds after WeavEHR's case origin, and stay ends differ by construction.
Such differences appear in `window_summary`/`window_differences`, not as
identifier mismatches. HiRID raw stay tables
remain supported: WeavEHR's HiRID `subject_id` is the native `patientid`, the
same column RICU uses as its ICU stay ID.

When an AUMC WeavEHR workspace is used without an explicit stay-table override,
the workflow automatically builds normalized ICU windows from the WeavEHR
`VISIT_START.parquet` and `VISIT_END.parquet` extraction outputs (AUMC is
extracted through WeavEHR's OMOP `visit_occurrence` table). Concept
events that contain `visit_occurrence_id` are mapped directly by
`(subject_id, visit_occurrence_id)` rather than being joined to every stay of
the same patient. This preserves admission provenance and prevents events from
one admission being assigned to another admission of the same patient.

WeavEHR concept outputs only contain `visit_occurrence_id` if the concept step
keeps it as a dataset-level extension column:

```yaml
# WeavEHR concept step config
config:
  mapping_configs:
    - name: aumc
      version: "1.5.0"
      extension_columns:
        visit_occurrence_id: col("visit_occurrence_id")
        # recommended for version provenance and item-level review (see below)
        dataset_version: col("version")
        source_code: col("code")
```

WeavEHR writes extension columns as strings; they are cast to integers here.
Concept parquets without the column fall back to joining on `subject_id` and
the ICU time window. In current WeavEHR, dataset-level `extension_columns` are
applied to simple concepts only, so derived concepts use this fallback.

### HiRID stay windows

Without an explicit stay table, HiRID stay windows follow RICU: they start at
the WeavEHR `ICU_ADMISSION` event and end at the latest `OBSERVATION` event of
the patient.

## Configuration

Notebook defaults can be overridden with environment variables:

| Variable | Purpose |
|---|---|
| `WEAVEHR_YAIB_OUTPUT_ROOT` | default output root (otherwise `~/output/weavehr_yaib`) |
| `WEAVEHR_YAIB_ICUSTAYS_CSV` | explicit raw ICU stay table |
| `WEAVEHR_YAIB_<DATASET>_STAYS` | dataset-specific raw ICU stay table, e.g. `WEAVEHR_YAIB_EICU_CRD_STAYS` |
| `WEAVEHR_YAIB_DATA_ROOT` | root searched for raw stay tables of the WeavEHR dataset version (falls back to `RICU_DATA_PATH`) |
| `WEAVEHR_YAIB_RICU_CONCEPT_DICT` | RICU `concept-dict.json` |
| `RICU_DYNAMIC_VARS` | comma-separated RICU variables exported by the R scripts |
| `RICU_SOURCE_VERSION` | declared version of the RICU source data, recorded by the R export |

The config-file mode of the `weavehr-yaib` CLI uses `example/config/weavehr_yaib.yml` as a template:

```bash
weavehr-yaib --config example/config/weavehr_yaib.yml
# several WeavEHR dataset versions in the project:
weavehr-yaib --config example/config/weavehr_yaib.yml --dataset-version 2.2
```

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

The tests use synthetic data only and need no WeavEHR installation. To generate real concept outputs, install and run WeavEHR separately (it requires Python ≥ 3.13), for example from a local checkout with `python -m pip install -e /path/to/WeavEHR` or `uv sync` inside that checkout.

## Main Python API

```python
from weavehr_yaib import write_all_concepts_wide

result = write_all_concepts_wide(
    dataset="eicu-crd",
    weavehr_output="/path/to/project/workspace",
    max_hours=None,
)
```

Using `max_hours=None` performs the general wide-table export without imposing the 168-hour validation window.

For the RICU-backed comparison workflow, the dataset notebooks call `build_and_write_yaib_wide_for_dataset(...)` and `compare_weavehr_wide_to_ricu_for_dataset(...)`. The reports produced by `weavehr_yaib.compare` are intended as complementary diagnostics and should be interpreted individually.

## Repository layout

```text
configs/                     # RICU/YAIB concept + unit mappings
example/datasets/            # exactly one .ipynb per dataset
example/notebooks/archive/   # historical pre-WeavEHR notebooks (not maintained)
scripts/datasets/            # one .R wrapper per RICU-backed dataset
scripts/                     # shared R export implementation
src/weavehr_yaib/
  all_concepts.py             # all-WeavEHR-concept wide export + output placement
  workspace.py                # WeavEHR project/workspace layout and step output lookup
  datasets.py                 # canonical dataset/RICU registry
  stays.py                    # dataset-specific stay table discovery/mapping
  transform.py                # YAIB/RICU-compatible dynamic transform
  compare.py                  # overlap/difference/reproduction diagnostics
  versions.py                 # dataset-version provenance and validation levels
  stay_ids.py                 # stay identifier spaces and stay crosswalks
  item_review.py              # item-level review tables for medical experts
  workflow.py                 # notebook-friendly bounded validation workflow
```
