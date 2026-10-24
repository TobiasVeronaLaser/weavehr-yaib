# WeavEHR ↔ YAIB / RICU validation

## Goal

Validate WeavEHR-generated YAIB-compatible concepts against RICU references.

The current validation focuses on the 48 dynamic YAIB variables. After the
feature-level validation is complete, derived outcomes/cohorts such as AKI,
mortality, sepsis, and potentially kidney-function-related tasks will be
validated separately.

Unresolved technical discrepancies will be documented and forwarded to
a medical reviewer for clinical review. If the validation results are
satisfactory, the WeavEHR ↔ YAIB comparison will be prepared for inclusion
in the paper.

---

## Current dataset-level status

### eICU-CRD

- Dynamic variables evaluated: 48
- Concepts above the provisional 1% presence-disagreement threshold: 0 / 48
- Current status: no major discrepancies identified

### MIMIC-IV

- Dynamic variables evaluated: 48
- Concepts above the provisional 1% presence-disagreement threshold: 2 / 48
- WeavEHR dataset version: MIMIC-IV 3.1
- RICU reference version: MIMIC-IV 2.2

#### `bili_dir`

Presence disagreement is approximately 1.54%.

Within the official validation scope:

- both non-null: 9,883
- only WeavEHR: 154
- only RICU: 1
- WeavEHR non-null: 10,038
- RICU non-null: 9,884

Shared values are effectively identical:

- mean absolute difference: approximately `4.82e-11`
- median absolute difference: `0`
- maximum absolute difference: approximately `4.77e-7`

WeavEHR and RICU both use MIMIC-IV `labevents.itemid = 50883` for direct
bilirubin, so the discrepancy is not explained by a different source-item
mapping.

RICU defines a valid range of 0 to 50 mg/dL for `bili_dir`. The WeavEHR-only
values inspected within the normalized comparison data were all below 50 mg/dL,
so the RICU upper-range filter does not explain the observed presence
difference.

The remaining discrepancy is therefore consistent with dataset-version,
stay-scope, measurement-timing, or source-coverage differences between
MIMIC-IV 3.1 and the RICU MIMIC-IV 2.2 reference.

#### `bnd`

Presence disagreement is approximately 1.01%.

Within the official validation scope:

- both non-null: 16,682
- only WeavEHR: 163
- only RICU: 7
- WeavEHR non-null: 16,846
- RICU non-null: 16,689

For all shared non-null values:

- mean absolute difference: `0`
- median absolute difference: `0`
- maximum absolute difference: `0`

WeavEHR and RICU both use MIMIC-IV `labevents.itemid = 51144` for band-form
neutrophils, so the discrepancy is not explained by a different source-item
mapping.

No value-transformation discrepancy has been identified on shared keys.

The unmatched `bnd` values were additionally inspected for an obvious
value-dependent filtering pattern. The WeavEHR-only values span a regular range
from 0 to 49%, while the small RICU-only subset spans 0 to 8%. No specific
threshold or boundary pattern was identified.

The remaining difference is therefore a presence/coverage discrepancy and is
consistent with dataset-version, stay-scope, measurement-timing, or
source-coverage differences between MIMIC-IV 3.1 and the RICU MIMIC-IV 2.2
reference.

### HiRID

- Dynamic variables evaluated: 48
- Concepts above the provisional 1% presence-disagreement threshold: 1 / 48

Current notable findings:

- `mchc`: approximately 98.77% presence disagreement
- `lymph`: approximately 0.005% presence disagreement
- `urine`: 0% presence disagreement

#### `mchc`

The HiRID `mchc` discrepancy is explained by a reference-side conversion and
range-filtering difference rather than by missing WeavEHR source coverage.

WeavEHR maps HiRID variable `24000170` and converts the reported MCHC values
from g/L using a factor of `0.1`, yielding values in the expected g/dL / `%`
scale.

Observed WeavEHR output:

- raw concept rows: 223,062
- non-null rows: 223,062
- subjects with values: 30,850
- unique subject/time pairs: 103,775
- value range: approximately 26.2 to 41.3
- median: approximately 33.8

RICU uses the same HiRID variable ID but applies a factor of `0.16114` and
defines the valid `mchc` range as 20 to 50.

Observed RICU output:

- non-null hourly values: 1,554
- patients with values: 830
- value range: approximately 42.21868 to 49.9534

The RICU behaviour was reproduced from the WeavEHR values by applying the
relative scaling factor `0.16114 / 0.1 = 1.6114` followed by the RICU range
filter `20 <= mchc <= 50`:

- surviving raw WeavEHR rows: 4,682
- surviving subjects: 830
- surviving unique subject/time pairs: 1,554
- surviving unique subject/hour pairs: 1,554
- converted value range: approximately 42.21868 to 49.9534

The reproduced subject count, hourly count, minimum and maximum match the RICU
output. The approximately 98.77% presence disagreement is therefore attributable
to the differing RICU conversion and subsequent upper-range filtering, not to a
WeavEHR extraction or mapping coverage defect.

#### `lymph`

`lymph` shows approximately 0.005% presence disagreement and reproduces the
RICU reference closely.

#### `urine`

`urine` shows 0% presence disagreement and reproduces the RICU reference
closely at the current aggregate comparison level.

HiRID stores urine output as a cumulative signal. WeavEHR reproduces RICU's
de-accumulation logic using the equivalent of `c(x[1], diff(x))`, with negative
differences clamped to zero.

A missing-value edge case was identified in the initial implementation:
for a sequence `[100, NA, 150]`, the transformer incorrectly produced
`[100, NA, 150]` because a missing previous value was treated like the first
observation of a subject.

RICU's corresponding behaviour was verified directly as:

`[100, NA, 150] -> [100, NA, NA]`

The WeavEHR transformer was corrected so that only the actual first record of
each subject keeps its original cumulative value. A regression test covering
this missing-value case was added.

HiRID transformer test result after the fix:

- 6 / 6 tests passed
- missing-value de-accumulation regression test passed

The known HiRID `urine` implementation edge case is therefore resolved.

---

## AUMC 1.5.0 vs RICU AUMC 1.0.2

### Comparison scope

- WeavEHR dataset version: AUMC 1.5.0
- WeavEHR representation: OMOP
- RICU reference version: AUMC 1.0.2
- RICU representation: native AUMC tables
- Validation window: 168 h
- Dynamic YAIB variables: 48

### Stay-ID correspondence

Before applying the RICU stay-window filtering:

- WeavEHR stays: 23,106
- RICU stays: 23,106
- shared numeric IDs: 23,106
- WeavEHR-only IDs: 0
- RICU-only IDs: 0

The observed numeric ID sets are therefore identical.

However:

- WeavEHR uses OMOP `visit_occurrence_id`
- RICU uses native AUMC `admissionid`

No documented OMOP-to-native ID crosswalk has yet been identified.

The observed equality is therefore treated as empirical evidence of
correspondence in the evaluated exports, not as a formally documented
identifier mapping.

### Time normalization

WeavEHR uses admission-relative integer hour indices from 0 to 168.

RICU AUMC `measuredat` values are normalized to hours and filtered using the
RICU stay windows before comparison.

After correct RICU normalization:

- WeavEHR rows: 1,390,441
- RICU rows: 1,153,001
- WeavEHR stays: 23,106
- RICU stays: 21,285
- shared `(stay_id, time)` keys: 1,153,001
- RICU-only keys: 0
- WeavEHR-only keys: 237,440
- RICU key overlap in WeavEHR: 100%
- WeavEHR key overlap in RICU: approximately 82.92%

### Scope / stay-window differences

The 237,440 WeavEHR-only hourly keys are not only empty grid rows.

Among them:

- rows with at least one concept value: 198,757
- stays with at least one concept value: 4,041

The additional WeavEHR rows can be separated into two groups.

#### RICU-missing stays

- complete stays absent after RICU normalization: 1,821
- WeavEHR rows belonging to these stays: 129,198
- rows containing values: 124,758
- stays containing values: 1,809

#### Additional hours on shared stays

- shared stays with additional WeavEHR hours: 15,251
- additional WeavEHR rows: 108,242
- additional rows containing values: 73,999
- shared stays with value-containing additional hours: 2,232

These findings indicate meaningful stay/window differences between the
WeavEHR AUMC 1.5.0 representation and the RICU AUMC 1.0.2 reference.

These scope differences must be evaluated separately from concept-mapping and
value differences.

### Concept-level comparison

To avoid mixing concept differences with stay-window differences, the current
concept-level comparison is restricted to `(stay_id, time)` keys present on
both sides.

The following provisional metric is used for technical triage:

`presence_disagreement_pct = 100 * (only_weavehr + only_ricu) / (both + only_weavehr + only_ricu)`

Current result:

- concepts evaluated: 48
- concepts above 1% presence disagreement: 47 / 48
- only `o2sat` is currently below 1% at approximately 0.67%

Examples of major discrepancies:

- `ckmb`: approximately 99.32%
- `methb`: approximately 99.11%
- `neut`: approximately 84.01%
- `lymph`: approximately 78.94%
- `mchc`: approximately 76.41%
- `urine`: approximately 5.08%
- `resp`: approximately 4.48%
- `hr`: approximately 1.52%
- `bili_dir`: approximately 1.45%
- `o2sat`: approximately 0.67%

These results must NOT currently be interpreted as 47 incorrect WeavEHR
concept implementations.

Potential technical causes include:

- AUMC version differences
- OMOP `concept_id` versus native AUMC `itemid`
- different item coverage
- unit differences
- transformation differences
- stay/window differences

### Item-level review

For AUMC:

- WeavEHR item representation: OMOP `concept_id`
- RICU item representation: native AUMC `itemid`
- no verified native-AUMC-`itemid` → OMOP-`concept_id` crosswalk is available

Numeric identifier equality must therefore not be interpreted as item
equivalence. Item comparisons are treated as side-by-side evidence using
labels, observed counts, source coverage and concept-level behaviour.

The generated item-review artifacts are located under:

`workspace/yaib/aumc/item_review/weavehr-1.5.0__ricu-aumc-1.0.2/`

The versioned validation artifacts stored under `docs/validation/` are:

- `aumc_ricu_items.csv`: observed native RICU AUMC items and aggregate counts
- `aumc_omop_measurement_multiplicity.csv`: OMOP measurement multiplicity diagnostics
- `aumc_review_candidates_triaged.csv`: complete technical classification of all 48 concepts and the focused medical-review candidates

Intermediate analysis tables used to derive the final classification are kept local
during validation and are not treated as final versioned artifacts.

### AUMC OMOP measurement multiplicity

During item-level investigation, several AUMC 1.5.0 OMOP measurement sources
were found to contain multiple distinct `measurement_id` records representing
the same semantic measurement within the same visit.

For the investigated sources, this was not introduced by the WeavEHR concept
mapping step. The records were already distinct in the AUMC OMOP extraction
output and differed at least by `measurement_id`.

A systematic 2x pattern was observed for several relevant OMOP concepts,
including:

- albumin (`3024561`)
- fibrinogen (`3016407`)
- INR / prothrombin time (`3032080`)
- MCV (`3023599`)
- multiple urine-output OMOP concepts

This multiplicity was used only as a diagnostic adjustment for item-count
analysis. The original concept outputs and presence-disagreement metrics were
not modified.

Examples:

- `albumin`: after adjustment, unmatched counts are nearly identical to RICU;
  only a small additional WeavEHR albumin source remains
- `fibrinogen`: after adjustment, the remaining 35-row difference corresponds
  to a small RICU item absent from WeavEHR
- `mcv`: after adjustment, the main source aligns closely with RICU, with a
  small additional WeavEHR source remaining
- `urine`: multiplicity explains most of the raw count difference, but
  additional urine-output source coverage remains
- `inr_pt`: multiplicity explains part of the count difference, but a large
  residual source/mapping difference remains

The multiplicity effect does not explain the major discrepancies for concepts
such as `ckmb`, `methb`, `mchc`, `ptt`, `cl` or `lymph`.

### Interpretation of item counts versus presence disagreement

Item-level observed counts and shared-key presence disagreement measure
different properties and must not be conflated.

For example, some concepts have nearly matching item counts after technical
adjustment but still show substantial presence disagreement on shared
`(stay_id, time)` keys. This indicates that similar total numbers of
measurements can be distributed differently across stays or hours.

Relevant causes may include:

- AUMC dataset-version differences
- OMOP versus native source representation
- visit/stay assignment
- measurement timing
- differences in item coverage

Therefore, item-count agreement is supporting mapping evidence, not proof of
equivalent concept-level output.

### Review procedure

For concepts above the provisional 1% presence-disagreement threshold:

1. Compare WeavEHR OMOP source concepts with the native RICU AUMC items.
2. Check for technical explanations including:
   - dataset-version differences
   - OMOP measurement multiplicity
   - OMOP versus native item representation
   - additional or missing source coverage
   - unit differences
   - transformation logic
   - stay/time-window differences
3. Document technically explainable discrepancies.
4. Forward only unresolved semantic or clinical mapping questions to a medical reviewer.
5. Record whether a WeavEHR implementation change is required.

### Current medical-review candidates

All 48 AUMC concepts now have a technical classification.

For 24 concepts, item-level coverage shows no unresolved mapping difference:
21 have exact aggregate observation-count matches between WeavEHR and RICU,
and 3 have complete exact individual item-count matches. Their remaining
shared-key presence differences are therefore not explained by item coverage
and are consistent with dataset-version, stay/visit assignment, measurement
timing, or source-representation differences.

Technical triage reduced the 48 AUMC concepts to 10 concepts for focused
medical review:

| Concept | Presence disagreement | Technical issue | Medical-review question |
|---|---:|---|---|
| `ckmb` | 99.32% | Large mapping/version difference; no OMOP multiplicity effect | Is OMOP concept `3005785` (CK-MB mass / MB-Massa) appropriate for the YAIB `ckmb` concept? |
| `methb` | 99.11% | Very large additional Met-Hb/FMetHb source population | Should all Met-Hb/FMetHb variants represented by OMOP concept `3007930` be included? |
| `lymph` | 78.94% | Different lymphocyte source combinations | Which percentage and non-percentage lymphocyte measurements belong in the YAIB `lymph` concept? |
| `mchc` | 76.41% | Additional MCHC source variants | Are the additional LabZis2 / M.C.H.C. variants clinically equivalent and appropriate for inclusion? |
| `ptt` | 66.57% | Additional APTT/Cephaline-related sources | Should APTT, CEF-KAOL.T and Cephalinetyd variants be treated as equivalent for `ptt`? |
| `inr_pt` | 65.56% | 2x OMOP multiplicity plus a large residual source difference | Are all AUMC prothrombin-time/INR variants represented by OMOP concept `3032080` appropriate for `inr_pt`? |
| `cl` | 65.07% | Additional Astrup / ISE chloride sources | Should blood-gas/Astrup/ISE chloride measurements be pooled with standard laboratory chloride? |
| `temp` | 37.96% | Multiple measurement sites | Which temperature sites should be included in the YAIB `temp` concept? |
| `fio2` | 7.17% | Additional `O2 Volume` source | Does the AUMC `O2 Volume` source represent FiO2 sufficiently for inclusion? |
| `urine` | 5.08% | 2x OMOP multiplicity plus additional urine-output sources | Should spontaneous urine, nephrostomy drains, suprapubic/splint/incontinence and bladder-irrigation output be included in `urine`? |

Concepts such as `alb`, `fgn`, `mcv`, `cai`, `o2sat`, `plt`, `mch`, `hr`,
`tnt`, `dbp`, `sbp`, `map`, `resp` and `neut` currently have sufficiently
specific technical explanations that they do not require medical review at
this stage.

## Remaining technical tasks

- Prepare the 10 unresolved AUMC concepts for focused medical review.
- Investigate whether any technically identified AUMC missing/additional
  mappings require implementation changes after review.
- Investigate HiRID `mchc`.
- Fix and test the HiRID urine missing-value de-accumulation edge case.
- Investigate MIMIC-IV `bili_dir` and `bnd`.
- Run the relevant regression/full test suite for the validation tooling.
- Update the paper methodology/results once dynamic-feature validation is
  complete.
- After feature validation, validate derived outcomes/cohorts separately,
  including mortality, AKI and sepsis.

## Derived outcome/cohort validation

### YAIB/RICU eICU reference cohort reproduction

The original YAIB-cohorts implementation was executed against the local eICU
RICU reference data in order to obtain the original cohort attrition counts for
comparison with the WeavEHR-derived cohorts.

Reference environment:

- YAIB-cohorts commit: `74ac699`
- RICU: `0.6.3`
- R: `4.3.3`
- data.table: `1.18.4`
- dataset: eICU-CRD 2.0

Several environment and compatibility issues had to be resolved before the
original YAIB code could be executed reproducibly.

First, `RICU_CONFIG_PATH` was set globally to `/home/q039tl/ricu_config`, while
that directory did not contain a `concept-dict.json`. RICU 0.6.3 includes this
path in `config_paths()` and its dictionary merge fails when one of the
configured paths has no matching dictionary. For the reference runs, user
environment and profile loading were disabled with
`R_ENVIRON_USER=/dev/null` and `R_PROFILE_USER=/dev/null`, while
`RICU_DATA_PATH` and `RICU_SRC_LOAD` were set explicitly.

Second, the R package `units` was not installed although several RICU concepts
used by YAIB require unit-aware concepts. `units` 1.0.1 was installed against
the system `udunits2` library.

Third, the original YAIB helper `R/src/obs_time.R` was incompatible with the
installed data.table 1.18.4. The temporary column `...time` was referenced in a
data.table update join as `patients[x, end := pmin(end, ...time), on = c(ids)]`.

With current data.table NSE rules this was interpreted as a lookup for `.time`
in the calling scope. The reference checkout was therefore patched locally to
refer explicitly to the joined `i` table:
`patients[x, end := pmin(end, i....time), on = c(ids)]`.

This is treated as a local compatibility patch only. It does not change the
cohort logic or outcome definition.

#### Base cohort

The original YAIB eICU base cohort produced the following sequential
attrition:

- initial ICU stays: 200,859
- invalid ICU length of stay: 2 excluded, 200,857 remaining
- ICU length of stay < 6 h: 16,412 newly excluded, 184,445 remaining
- fewer than 4 measurement hours across the 48 dynamic variables: 410 newly
  excluded, 184,035 remaining
- more than 12 consecutive hours without measurements: 792 newly excluded,
  183,243 remaining
- age < 18 years: 455 newly excluded, 182,788 remaining

The final original YAIB/RICU eICU base cohort therefore contains **182,788
stays**.

The earlier WeavEHR-derived Python reconstruction produced 181,738 stays. The
largest discrepancy appears at the `<4 measurement hours` exclusion: the
original YAIB/RICU reference excludes only 410 additional stays at this step,
whereas the WeavEHR-derived reconstruction excluded 1,465. This indicates that
the main cohort difference is already introduced by measurement coverage across
the 48 dynamic variables rather than by the later age or observation-gap
criteria.

#### Mortality24 cohort

The original YAIB mortality task was then executed using the same reference
environment and base-cohort logic.

Sequential mortality-specific attrition:

- after exclusion of deaths within the first 30 h: 179,705 stays remain;
  3,083 newly excluded at this step
- after exclusion of ICU stays shorter than 30 h: 113,381 stays remain;
  66,324 newly excluded at this step

The final original YAIB/RICU eICU Mortality24 cohort therefore contains
**113,381 stays**.

The previous WeavEHR-derived reconstruction produced 113,076 stays. Because the
reference base cohort already differs before the mortality-specific exclusion
steps, the Mortality24 difference must be interpreted in the context of the
upstream base-cohort measurement-coverage discrepancy.

The YAIB mortality task uses eventual ICU mortality as the label, while the
predictor window is limited to the first 24 hours and eligibility requires at
least 30 hours of ICU stay or survival. This validation is therefore distinct
from the repository's separate in-hospital-mortality concept validation below.

#### AKI cohort

The original YAIB AKI task was executed for eICU using the same reference
environment and the locally patched YAIB checkout described above.

Starting from the original YAIB/RICU base cohort of 182,788 stays, the
sequential AKI-specific attrition was:

- eICU hospital-level AKI-prevalence exclusion: 20 newly excluded, 182,768
  remaining
- AKI onset within the first 6 h: 9,876 newly excluded, 172,892 remaining
- baseline creatinine > 4 mg/dL: 8,010 newly excluded, 164,882 remaining

The final original YAIB/RICU eICU AKI cohort therefore contains **164,882
stays**.

The generated hourly outcome table contains 6,628,740 rows:

- positive hourly AKI labels: 792,371
- negative hourly AKI labels: 5,836,369
- missing hourly labels: 0

Aggregated to the stay level:

- stays with at least one positive AKI label: 62,313
- stays without a positive AKI label: 102,569
- stays with all AKI labels missing: 0

The hourly label counts must not be interpreted as patient counts because the
YAIB AKI outcome is represented on the hourly prediction grid.

### In-hospital mortality

#### MIMIC-IV

WeavEHR MIMIC-IV 3.1 in-hospital mortality was compared against the RICU
MIMIC-IV reference definition. RICU defines in-hospital mortality from
`admissions.hospital_expire_flag == 1`.

The WeavEHR concept output contains one event per hospital admission at
`dischtime`. The combination of `subject_id` and `dischtime` is unique in the
RICU admissions table and was therefore used for the row-level comparison.

Results:

- WeavEHR rows: 546,028
- RICU rows: 546,028
- shared rows: 546,028
- only WeavEHR: 0
- only RICU: 0
- equal mortality values: 546,028
- different mortality values: 0
- mortality = 0: 534,227
- mortality = 1: 11,801

Thus, MIMIC-IV in-hospital mortality is reproduced exactly by WeavEHR for the
evaluated admissions.

The installed RICU 0.6.3 concept-dictionary parser could not directly load the
`death` concept in this environment. The RICU package definition was therefore
verified from its shipped `concept-dict.json`, and the reference was reproduced
directly from RICU's imported MIMIC-IV `admissions` table using the specified
`hospital_expire_flag == 1` transformation.


#### eICU

RICU defines eICU in-hospital mortality from
`patient.hospitaldischargestatus == "Expired"`.

The raw eICU patient table contains 200,859 ICU stays but only 166,355 unique
hospital stays (`patienthealthsystemstayid`). WeavEHR produces one
in-hospital-mortality event per hospital stay, so the apparent difference of
34,504 rows is entirely explained by multiple ICU stays belonging to the same
hospital admission.

Additional checks showed:

- ICU stays: 200,859
- hospital stays: 166,355
- hospital stays with more than one ICU stay: 27,635
- extra ICU stays beyond one per hospital stay: 34,504
- hospital stays with conflicting non-null discharge status: 0

The hospital-level comparison used
`patienthealthsystemstayid == WeavEHR subject_id`.

Results:

- WeavEHR rows: 166,355
- RICU hospital-level rows: 166,355
- shared non-null status values: 164,875
- equal shared status values: 164,875
- different shared status values: 0
- only WeavEHR status: 0
- only RICU status: 0
- both missing: 1,480
- Alive: 150,252
- Expired: 14,623

Thus, eICU in-hospital mortality is reproduced exactly by WeavEHR at the
hospital-admission level. The lower row count relative to the raw eICU patient
table reflects the intended aggregation from ICU stays to hospital stays rather
than missing outcome coverage.


#### HiRID

WeavEHR HiRID 1.1.1 in-hospital mortality was compared against the HiRID
discharge status used by RICU.

The HiRID `general` table contains one row per patient and 33,905 patients in
total. WeavEHR likewise produces exactly one in-hospital-mortality row per
patient.

Status counts are identical:

- alive: 31,604
- dead: 2,062
- missing: 239

The row-level comparison used `patientid == WeavEHR subject_id`.

Results:

- WeavEHR rows: 33,905
- RICU/reference rows: 33,905
- shared non-null status values: 33,666
- equal shared status values: 33,666
- different shared status values: 0
- only WeavEHR status: 0
- only RICU/reference status: 0
- both missing: 239
- equal including missing values: 33,905
- WeavEHR dead patients: 2,062
- RICU/reference dead patients: 2,062
- dead patients only in WeavEHR: 0
- dead patients only in RICU/reference: 0

RICU's HiRID `death` definition uses observation variables 110 and 200 to
determine the event time and retains patients whose `general.discharge_status`
is `dead`. There are 33,897 patients with at least one observation of variable
110 or 200. All 2,062 dead patients have such an observation; therefore no
death is lost through RICU's event-time construction.

Thus, HiRID in-hospital mortality status is reproduced exactly by WeavEHR.

The final mortality comparisons for MIMIC-IV, eICU and HiRID were additionally
rerun through the repository's reproducible outcome-validation helpers. All
three comparisons produced zero disagreement rows. The generated summaries and
disagreement tables are stored under
`docs/validation/outcomes/in_hospital_mortality/`.
