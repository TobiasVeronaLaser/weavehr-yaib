# YAIB/RICU eICU cohort and outcome reference reproduction

## Purpose

This document records the reproduction and source-level interpretation of the
original YAIB/RICU eICU cohort and outcome logic used as the reference for the
WeavEHR → YAIB interoperability experiment.

It is intended to preserve exact methods, attrition counts, compatibility
adjustments and semantic findings for later issue tracking and manuscript use.

The reference reproduction is distinct from the final WeavEHR substitution
experiment: the purpose here is to establish what the original YAIB/RICU
pipeline actually does before replacing RICU upstream.

## Reference environment

- YAIB-cohorts commit: `74ac699`
- RICU: `0.6.3`
- R: `4.3.3`
- data.table: `1.18.4`
- units: `1.0.1`
- dataset: eICU-CRD 2.0
- observation horizon: 168 h for the base dynamic-feature workflow

Clean reference execution used explicit RICU data/source settings while user
environment/profile loading was disabled to avoid an unrelated global
`RICU_CONFIG_PATH`.

## Compatibility adaptations

The reference checkout required local compatibility adaptations for the current
R/data.table environment.

### Observation-time join

`R/src/obs_time.R` referenced the joined temporary column `...time` through
data.table NSE. The local reference checkout was adapted to explicitly use the
joined `i` table (`i....time`).

This is treated as an execution compatibility adaptation, not a cohort-semantic
change.

### Sepsis callback argument

The top-level Sepsis-3 callback was adapted to explicitly accept the propagated
`si_mode` argument so that it was not interpreted as an additional recursive
concept input.

### Sepsis hospital-prevalence join

The eICU hospital-prevalence helper was adapted from an implicit data.table join
to an explicit join on the concept identifier.

These adaptations preserve the intended cohort and task logic.

## Base cohort

Sequential original YAIB/RICU eICU attrition:

| Step | Newly excluded | Remaining |
|---|---:|---:|
| Initial ICU stays | — | 200,859 |
| Invalid ICU length of stay | 2 | 200,857 |
| ICU length of stay < 6 h | 16,412 | 184,445 |
| Fewer than 4 measurement rows/hours in the loaded 48-variable dynamic representation | 410 | 184,035 |
| More than 12 consecutive hours without measurements | 792 | 183,243 |
| Age < 18 years | 455 | **182,788** |

Final reference base cohort: **182,788 stays**.

### Important semantic finding

The `<4 measurements` exclusion must be reproduced according to the object
returned by the original YAIB/RICU loading workflow. It is not equivalent to
counting non-null cells on a fully expanded per-stay hourly grid.

This distinction is important for the WeavEHR substitution because an earlier
Python reconstruction used a different representation and therefore produced a
different exclusion count.

The reference implementation must be reproduced semantically rather than forced
to agree through post-hoc filtering.

## Mortality24

Starting from the reference base cohort:

| Step | Newly excluded | Remaining |
|---|---:|---:|
| Death within first 30 h | 3,083 | 179,705 |
| ICU stay shorter than 30 h | 66,324 | **113,381** |

Final reference Mortality24 cohort: **113,381 stays**.

The task uses eventual ICU mortality as the outcome while restricting the
predictor window to the first 24 h and applying the 30 h eligibility rule.

This task must therefore not be conflated with the separate harmonized
`in_hospital_mortality` concept comparison.

## AKI

Starting from the reference base cohort:

| Step | Newly excluded | Remaining |
|---|---:|---:|
| eICU hospital-level AKI-prevalence exclusion | 20 | 182,768 |
| First AKI onset within first 6 h | 9,876 | 172,892 |
| Baseline creatinine > 4 mg/dL | 8,010 | **164,882** |

Final reference AKI cohort: **164,882 stays**.

Reference hourly outcome table:

- rows: 6,628,740
- positive labels: 792,371
- negative labels: 5,836,369
- missing labels: 0

Stay-level summary:

- at least one positive AKI label: 62,313 stays
- no positive AKI label: 102,569 stays
- all labels missing: 0 stays

### AKI semantic findings

The original YAIB AKI workflow:

- uses the first AKI event for early-onset exclusion;
- derives baseline creatinine from pre-ICU measurements plus the first
  in-ICU measurement;
- excludes baseline creatinine > 4 mg/dL;
- applies YAIB's original outcome-window logic on the hourly grid.

The final WeavEHR substitution must preserve this YAIB task logic rather than
introducing a bespoke WeavEHR-specific AKI task.

## Sepsis

Starting from the reference base cohort:

| Step | Newly excluded | Remaining |
|---|---:|---:|
| Low hospital-level sepsis prevalence | 172,085 | 10,703 |
| Sepsis onset within first 6 h | 121 | **10,582** |

Final reference Sepsis-3 cohort: **10,582 stays**.

Reference hourly outcome table:

- rows: 676,185
- positive labels: 481
- negative labels: 675,704
- missing labels: 0

Stay-level summary:

- at least one positive label: 37 stays
- no positive label: 10,545 stays
- all labels missing: 0 stays

## WeavEHR substitution work completed so far

The reference reproduction established the exact target behavior before
upstream substitution.

Subsequent WeavEHR-side investigation established that eICU contains two
different identity levels relevant to the substitution:

- WeavEHR `subject_id`: hospital-system stay identity
  (`patienthealthsystemstayid`)
- extracted `stay_id`: ICU unit-stay identity (`patientunitstayid`)

The eICU extraction tables already preserve `stay_id`.

Dataset-wide concept configuration was then used to preserve `stay_id` in the
simple concepts needed by YAIB. The 48 YAIB dynamic concepts were verified to
carry the ICU-stay identifier after regeneration.

A further issue was identified for complex/windowed concepts: their temporal
operations were partitioned only by `subject_id`. For eICU this permits
measurements from multiple ICU unit stays belonging to one hospital-system stay
to influence one another.

A synthetic AKI regression test demonstrated the issue: without stay-level
partitioning, a creatinine value from one ICU stay changed the computed AKI
stage in a second ICU stay under the same subject.

A generic WeavEHR fix is being developed so complex/windowed computations can
partition on `subject_id` plus configured dataset-level grouping columns such as
`stay_id`.

This issue must be resolved before the final WeavEHR → YAIB cohort comparison is
treated as valid.

## Interpretation rules for the final experiment

The final interoperability experiment will:

1. keep YAIB cohort/task logic unchanged;
2. replace the RICU-derived upstream inputs with WeavEHR-derived inputs;
3. compare resulting cohort membership, labels and downstream model behavior;
4. report genuine differences rather than modifying WeavEHR to force equality.

RICU/YAIB is therefore the reproducibility reference implementation, not an
assumed clinical gold standard.

## Current status

### Reference reproduction

- Base cohort: reproduced
- Mortality24: reproduced
- AKI: reproduced
- Sepsis-3: reproduced

### WeavEHR substitution

- 48 dynamic concepts: eICU stay identity preserved in simple concept outputs
- complex/windowed stay-level partitioning: implementation in progress
- final base-cohort substitution comparison: pending corrected complex/stay handling
- final Mortality24 substitution comparison: pending
- final AKI substitution comparison: pending
- final Sepsis substitution comparison: pending

## Manuscript-relevant evidence

The reference reproduction provides exact, version-pinned baseline cohort and
label counts against which the WeavEHR substitution can be evaluated.

The investigation also demonstrates why interoperability cannot be assessed by
matching final row counts alone: source identity, sparse-versus-expanded time
representations, pre-ICU history, temporal window semantics and ICU-stay
boundaries all affect cohort construction.

These implementation details should be reported as part of the validation
methodology rather than hidden through ad-hoc agreement corrections.
