# AUMC medical review results

## Purpose

This document records the completed medical review of the 10 AUMC concepts that
remained clinically or semantically unresolved after technical validation of
WeavEHR against the RICU/YAIB reference.

The purpose of this record is to preserve:

- the technical reason each concept was submitted for review;
- the medical review decision and rationale;
- the resulting implementation decision;
- unresolved follow-up questions;
- the interpretation relevant for later manuscript reporting.

This document is the result record. The original review material is retained in
`aumc_medical_review_packet.md`.

## Review status

Medical review was reported complete on 2026-10-27.

Review outcomes:

- **include:** 6 concepts
- **partial / conditional:** 2 concepts
- **uncertain:** 2 concepts
- **exclude:** 0 concepts

The review therefore shows that several large WeavEHR/RICU coverage differences
are clinically plausible consequences of broader WeavEHR source coverage rather
than evidence of incorrect concept mappings.

## Comparison context

- WeavEHR dataset: AUMC 1.5.0
- WeavEHR representation: OMOP
- RICU reference: AUMC 1.0.2
- RICU representation: native AUMC tables
- Validation window: 168 hours
- Technical triage metric: shared stay-hour presence disagreement
- Concepts submitted for review: 10
- Identifiers are not directly comparable:
  - WeavEHR uses OMOP `concept_id`
  - RICU uses native AUMC `itemid`
- No verified native-AUMC-itemid ↔ OMOP-concept-id crosswalk was used.

Observation counts are aggregate counts only.

## Decision summary

| YAIB concept | WeavEHR concept | Presence disagreement | Review decision | Implementation status |
|---|---|---:|---|---|
| `ckmb` | `creatine_kinase_MB` | 99.32% | uncertain | no mapping change; follow-up required |
| `methb` | `methemoglobin` | 99.11% | include | current inclusion clinically supported |
| `lymph` | `lymphocytes` | 78.94% | partial / conditional | separate percentage and absolute-count semantics |
| `mchc` | `mean_corpuscular_hemoglobin_concentration` | 76.41% | include | current inclusion clinically supported |
| `ptt` | `partial_thromboplastin_time` | 66.57% | include | current inclusion clinically supported |
| `inr_pt` | `prothrombin_time_international_normalized_ratio` | 65.56% | uncertain | no mapping change; PT/INR semantics require verification |
| `cl` | `chloride` | 65.07% | include | current inclusion clinically supported |
| `temp` | `temperature` | 37.96% | include | current measurement-site coverage clinically supported |
| `fio2` | `fraction_of_inspired_oxygen` | 7.17% | include | current inclusion clinically supported |
| `urine` | `urine_output` | 5.08% | partial / conditional | retain additional true urine sources; investigate bladder irrigation separately |

## Concept-level review

### 1. `ckmb` — `creatine_kinase_MB`

**Decision:** uncertain

**WeavEHR source**

- OMOP concept `3005785`
- `MB-Massa (bloed)`
- CK-MB mass concentration
- aggregate observations in review package: 59,014

**RICU reference**

- native item `6824`
- `CK-MB`
- aggregate observations: 2,315

**Technical finding**

No OMOP multiplicity effect explained the large source-coverage difference.

**Medical interpretation**

CK-MB mass is clinically a legitimate way to measure CK-MB and the source label
appears appropriate. However, the observed value distribution raised concern:
the reported median was approximately 17 in the reviewed data, while the
reviewer expected substantially lower normal CK-MB mass values. ICU case mix and
selective measurement can shift the distribution, but the magnitude warrants
further investigation.

**Implementation decision**

Do not change the mapping based on the review alone.

**Follow-up**

- verify units and unit conversion;
- inspect aggregate value distribution and outliers;
- confirm whether all events represented by OMOP concept `3005785` are CK-MB
  mass measurements with equivalent semantics.

**Paper interpretation**

The large disagreement remains clinically unresolved and must not be described
as either a confirmed WeavEHR error or a confirmed improvement over RICU.

---

### 2. `methb` — `methemoglobin`

**Decision:** include

**WeavEHR source**

- OMOP concept `3007930`
- Met-Hb / FMetHb variants

**Technical finding**

WeavEHR contains substantially more observations than the RICU native item.

**Medical interpretation**

The mapped Met-Hb/FMetHb sources are clinically appropriate. The larger number
of measurements is plausible because modern blood-gas analyzers routinely
produce methemoglobin measurements and the WeavEHR AUMC version includes a
different and more recent source population.

**Implementation decision**

Retain the current mapping. No clinical mapping reduction is indicated.

**Paper interpretation**

The high presence disagreement can plausibly reflect legitimate broader source
coverage rather than incorrect mapping.

---

### 3. `lymph` — `lymphocytes`

**Decision:** partial / conditional

**Technical finding**

RICU combines lymphocyte sources with different semantics, while WeavEHR OMOP
concept `3002030` represents lymphocytes per 100 leukocytes.

**Medical interpretation**

Lymphocyte percentage and absolute lymphocyte count are distinct measurements,
often obtained using different laboratory techniques, and should not be treated
as the same concept without explicit transformation.

**Implementation decision**

Do not combine percentage and absolute-count measurements under one simple
concept merely to reproduce RICU coverage.

The current percentage mapping should remain semantically explicit. A separate
implementation decision is required for absolute lymphocyte counts and for any
derived conversion using white blood cell count.

**Follow-up**

- identify the desired canonical semantics of the YAIB-facing `lymph` feature;
- determine whether separate percentage and absolute-count concepts are needed;
- evaluate whether a derived conversion using white blood cell count should be
  implemented rather than merging raw measurements.

**Paper interpretation**

The disagreement exposes a semantic difference between source harmonization
strategies rather than a simple missing-item error.

---

### 4. `mchc` — `mean_corpuscular_hemoglobin_concentration`

**Decision:** include

**WeavEHR source**

- OMOP concept `40762530`
- M.C.H.C. / MCHC / LabZis2 variants

**Medical interpretation**

The mapped variants are clinically equivalent MCHC measurements. LabZis2 is a
laboratory information-system designation rather than evidence of a different
clinical quantity.

An extreme maximum value was considered implausible and may represent a data
quality or decimal-point issue, but this does not invalidate the source mapping.

**Implementation decision**

Retain the current mapping.

**Follow-up**

Treat implausible extreme values as a separate value-quality/limits question,
not as a mapping-identity problem.

**Paper interpretation**

Additional WeavEHR source variants are medically supported.

---

### 5. `ptt` — `partial_thromboplastin_time`

**Decision:** include

**WeavEHR source**

- OMOP concept `3013466`
- APTT, CEF-KAOL.T and Cephalinetyd source labels

**Medical interpretation**

The reviewed variants represent equivalent aPTT-related assays. Cephaline and
kaolin are assay reagents associated with aPTT measurement, and the observed
ranges were considered plausible.

**Implementation decision**

Retain the current mapping.

**Paper interpretation**

The additional WeavEHR coverage is medically supported and should not be
interpreted as an erroneous broad mapping solely because it exceeds RICU
coverage.

---

### 6. `inr_pt` — `prothrombin_time_international_normalized_ratio`

**Decision:** uncertain

**WeavEHR source**

- OMOP concept `3032080`
- currently described in the WeavEHR mapping as INR in blood by coagulation assay

**Technical finding**

A systematic 2x OMOP measurement multiplicity effect exists, but substantial
residual source-coverage difference remains after considering multiplicity.

**Medical interpretation**

The reviewed value range was broadly compatible with INR, apart from an
implausible extreme maximum. However, prothrombin time and INR are not the same
quantity. INR is derived from prothrombin-time measurements and should not be
semantically merged with raw PT/Quick values.

**Implementation decision**

Do not change the mapping until the source semantics are verified.

**Follow-up**

- verify that OMOP concept `3032080` events are specifically INR;
- determine whether the RICU reference item represents INR, PT, or mixed
  semantics;
- ensure the YAIB-facing concept name and units match the actual measurement.

**Paper interpretation**

This concept remains unresolved because the central uncertainty is semantic,
not merely quantitative disagreement.

---

### 7. `cl` — `chloride`

**Decision:** include

**WeavEHR sources**

- OMOP concept `3014576`
- OMOP concept `3018572`
- standard chloride plus Astrup / ISE variants

**Medical interpretation**

The additional Astrup/ISE labels represent clinically compatible chloride
measurements. The reviewed value ranges were plausible.

**Implementation decision**

Retain both currently mapped chloride source groups.

**Paper interpretation**

The additional WeavEHR source coverage is clinically supported.

---

### 8. `temp` — `temperature`

**Decision:** include

**WeavEHR source sites**

- blood
- esophageal
- bladder
- rectal
- axillary
- oral
- tympanic

**Medical interpretation**

All reviewed sites are clinically useful ways of measuring body temperature and
can reasonably contribute to the harmonized temperature concept. Axillary
temperature could be treated more conservatively in some analyses, but the
review did not recommend excluding it.

Several maximum values around 360–370 °C are physiologically impossible and
likely reflect decimal-point/data-quality problems.

**Implementation decision**

Retain the current measurement-site coverage.

**Follow-up**

Investigate implausible extreme temperature values separately from mapping
identity.

**Paper interpretation**

The broader WeavEHR temperature coverage is medically supported.

---

### 9. `fio2` — `fraction_of_inspired_oxygen`

**Decision:** include

**WeavEHR sources**

- OMOP concept `3025408`
- OMOP concept `3020716`

**Medical interpretation**

The additional O2 Volume source had a clinically plausible range consistent
with FiO2 use in the ICU.

**Implementation decision**

Retain both currently mapped source groups.

**Paper interpretation**

The additional WeavEHR source is clinically supported.

---

### 10. `urine` — `urine_output`

**Decision:** partial / conditional

**WeavEHR sources reviewed**

The WeavEHR mapping includes standard urine output as well as additional source
types such as spontaneous urine, nephrostomy-related output and other urinary
drainage sources.

**Medical interpretation**

The additional genuine urine-output sources are useful and their absence from
RICU was considered a weakness of the narrower reference definition.

Bladder irrigation output (`Spoelblaas`) is different. Irrigation introduces
fluid into the bladder, so drainage volume cannot be interpreted directly as
urine production without accounting for irrigation input. Including this
volume unconditionally can overestimate true urine output.

Extreme negative and very large values were also noted and should be treated as
data-quality questions.

**Implementation decision**

Retain additional genuine urine-output sources.

Do not make a blanket decision on the entire OMOP concept solely from its
concept ID. Investigate whether `Spoelblaas` can be identified and excluded or
represented separately at source-label/provenance level without removing valid
urine measurements grouped under the same OMOP concept.

**Follow-up**

- inspect source-level provenance for `Spoelblaas`;
- determine whether the source can be filtered separately;
- evaluate implausible negative/extreme values independently;
- re-run urine validation after any mapping refinement.

**Paper interpretation**

RICU's narrower urine definition does not constitute a clinical gold standard:
some additional WeavEHR sources are explicitly supported by medical review.
Bladder-irrigation output remains a specific exception requiring refinement.

## Implementation categories after review

### Clinically confirmed — retain current mappings

- `methb`
- `mchc`
- `ptt`
- `cl`
- `temp`
- `fio2`

These concepts require documentation and regression validation, but the medical
review does not call for narrowing their current source mappings.

### Partial / conditional — separate implementation work

- `lymph`
- `urine`

These should be handled in concept-specific changes with their own validation,
rather than folded into a broad "medical review fixes" change.

### Uncertain — no mapping change yet

- `ckmb`
- `inr_pt`

Uncertainty must remain visible. Neither concept should be altered merely to
reduce disagreement with RICU.

## Manuscript-relevant conclusions

1. A high WeavEHR/RICU presence disagreement does not by itself imply an
   incorrect WeavEHR mapping.
2. For six of the ten clinically reviewed AUMC concepts, broader WeavEHR source
   inclusion was judged clinically appropriate.
3. Two concepts revealed conditional semantic issues that require targeted
   implementation decisions rather than simple reference matching.
4. Two concepts remain unresolved and must be reported as such until additional
   source-semantic or value-distribution evidence is available.
5. RICU is used as a reproducibility/reference implementation, not as an
   unquestioned clinical gold standard for source coverage.
