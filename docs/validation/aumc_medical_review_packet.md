# AUMC medical review package

## Purpose

This document contains the AUMC concepts that remain clinically or semantically unresolved after technical validation of WeavEHR against the RICU/YAIB reference.

Only concepts for which a medical mapping decision is still required are included here.

## Comparison context

- WeavEHR dataset: AUMC 1.5.0
- WeavEHR representation: OMOP
- RICU reference: AUMC 1.0.2
- RICU representation: native AUMC tables
- Validation window: 168 hours
- Technical triage metric: shared stay-hour presence disagreement
- Concepts submitted for medical review: 10

### Important identifier note

WeavEHR uses OMOP `concept_id`, while RICU uses native AUMC `itemid`.
No verified native-AUMC-itemid to OMOP-concept-id crosswalk is available.
The identifiers below are therefore shown side by side and must not be interpreted as direct numeric mappings.

Observation counts are aggregate counts only; no patient-level records or patient identifiers are included in this review package.

## Requested review

For each concept, please assess whether the WeavEHR source measurements listed below are clinically appropriate for the corresponding YAIB/RICU concept.

Suggested decisions:

- **include** — source belongs in the concept
- **exclude** — source should not be part of the concept
- **partial / conditional** — only some variants should be included
- **uncertain** — further domain/context information is required

## 1. `ckmb` — `creatine_kinase_MB`

**Presence disagreement:** 99.32%

**WeavEHR / OMOP sources**

3005785 | MB-Massa (bloed)//µg/l | measurement | n=59014

**RICU / native AUMC reference sources**

6824 | CK-MB | numericitems | n=2315

**Technical finding**

No OMOP multiplicity effect detected. WeavEHR OMOP concept 3005785 contains far more observations than the RICU reference item, indicating a substantial source-coverage difference.

**Medical review question**

Is AUMC OMOP concept 3005785 (MB-Massa / CK-MB mass) clinically equivalent to the RICU CK-MB concept and appropriate for inclusion?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 2. `methb` — `methemoglobin`

**Presence disagreement:** 99.11%

**WeavEHR / OMOP sources**

3007930 | FMetHb//None; Met-Hb  (bloed)//Geen; Met-Hb (bloed)//Geen | measurement | n=336872

**RICU / native AUMC reference sources**

11692 | Met-Hb (bloed) | numericitems | n=2714

**Technical finding**

No OMOP multiplicity effect detected. WeavEHR includes a substantially larger Met-Hb/FMetHb source population than the RICU reference.

**Medical review question**

Should all Met-Hb/FMetHb source variants represented by OMOP concept 3007930 be included in the YAIB methemoglobin concept?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 3. `lymph` — `lymphocytes`

**Presence disagreement:** 78.94%

**WeavEHR / OMOP sources**

3002030 | Lymfocyten % (bloed)//Geen; Lymfocyten//None | measurement | n=4654

**RICU / native AUMC reference sources**

11846 | Lymfocyten % (bloed) | numericitems | n=4606 ; 14258 | Lymfocyten (bloed) | numericitems | n=11647

**Technical finding**

WeavEHR and RICU use different lymphocyte source combinations. RICU includes both percentage and other lymphocyte items; WeavEHR maps them differently into OMOP concept 3002030.

**Medical review question**

Which AUMC lymphocyte measurements belong in the YAIB lymph concept, especially percentage versus non-percentage variants?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 4. `mchc` — `mean_corpuscular_hemoglobin_concentration`

**Presence disagreement:** 76.41%

**WeavEHR / OMOP sources**

40762530 | M.C.H.C.//mmol/l; MCHC (bloed)-LabZis2//mmol/cel; MCHC (bloed)//mmol/cel | measurement | n=8010

**RICU / native AUMC reference sources**

18666 | MCHC (bloed) | numericitems | n=2686

**Technical finding**

No OMOP multiplicity effect detected. WeavEHR includes additional MCHC source variants, including LabZis2/M.C.H.C., beyond the RICU item.

**Medical review question**

Are the additional MCHC variants (including LabZis2 and M.C.H.C.) clinically equivalent and appropriate for inclusion?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 5. `ptt` — `partial_thromboplastin_time`

**Presence disagreement:** 66.57%

**WeavEHR / OMOP sources**

3013466 | APTT  (bloed)//sec; APTT (bloed)//sec; CEF-KAOL.T (bloed)//sec; Cephalinetyd//sec | measurement | n=204872

**RICU / native AUMC reference sources**

17982 | APTT (bloed) | numericitems | n=68230

**Technical finding**

No OMOP multiplicity effect detected. WeavEHR includes substantially more APTT/Cephaline-related observations than RICU.

**Medical review question**

Should all APTT / CEF-KAOL.T / Cephalinetyd source variants be treated as equivalent for the YAIB ptt concept?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 6. `inr_pt` — `prothrombin_time_international_normalized_ratio`

**Presence disagreement:** 65.56%

**WeavEHR / OMOP sources**

3032080 | Prothrombinetijd  (bloed)//INR; Prothrombinetijd (bloed)//INR | measurement | n=387380

**RICU / native AUMC reference sources**

11893 | Prothrombinetijd (bloed) | numericitems | n=66847

**Technical finding**

OMOP concept 3032080 shows systematic 2x source multiplicity, but a large residual excess remains after adjustment. WeavEHR includes substantially more prothrombin/INR observations than RICU.

**Medical review question**

Are all AUMC prothrombin-time/INR source variants mapped to OMOP concept 3032080 clinically appropriate for the YAIB inr_pt concept?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 7. `cl` — `chloride`

**Presence disagreement:** 65.07%

**WeavEHR / OMOP sources**

3014576 | Chloor (bloed)//mmol/l; Chloor//mmol/l | measurement | n=180102 ; 3018572 | Chloor Astrup//mmol/l; Cl (onv.ISE) (bloed)//mmol/l | measurement | n=346818

**RICU / native AUMC reference sources**

9930 | Chloor (bloed) | numericitems | n=178659

**Technical finding**

WeavEHR includes a large additional chloride source group (Chloor Astrup / Cl onv.ISE) beyond the RICU chloride item.

**Medical review question**

Should blood-gas/Astrup/ISE chloride measurements be pooled with standard laboratory chloride for the YAIB cl concept?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 8. `temp` — `temperature`

**Presence disagreement:** 37.96%

**WeavEHR / OMOP sources**

21490586 | PiCCO Tb blood temperature//°C; Temp Bloed//°C | measurement | n=2004487 ; 21490588 | Temp Oesophagus//°C | measurement | n=833973 ; 21490870 | Temp Blaas//°C | measurement | n=927689 ; 3006322 | Temp Oraal//°C | measurement | n=546 ; 3022060 | Temp Rectaal//°C | measurement | n=387259 ; 3025085 | Temp Axillair//°C | measurement | n=202198 ; 3025163 | Temp Oor//°C | measurement | n=52540

**RICU / native AUMC reference sources**

13952 | Temp Blaas | numericitems | n=927689 ; 16110 | Temp Oesophagus | numericitems | n=833973 ; 8658 | Temp Bloed | numericitems | n=1999754

**Technical finding**

WeavEHR includes blood temperature plus rectal, axillary, ear and oral temperature sources, while RICU is narrower.

**Medical review question**

Which temperature measurement sites should be included in the YAIB temp concept?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 9. `fio2` — `fraction_of_inspired_oxygen`

**Presence disagreement:** 7.17%

**WeavEHR / OMOP sources**

3020716 | O2 Volume(2)//None; O2 Volume//None | measurement | n=85391 ; 3025408 | O2 concentratie//Geen; Zephyros O2i//Geen | measurement | n=15645447

**RICU / native AUMC reference sources**

12279 | O2 concentratie | numericitems | n=15645395

**Technical finding**

Main oxygen concentration source closely matches RICU, but WeavEHR additionally includes O2 Volume source variants.

**Medical review question**

Does the AUMC O2 Volume source represent FiO2 sufficiently to be included in the YAIB fio2 concept?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---

## 10. `urine` — `urine_output`

**Presence disagreement:** 5.08%

**WeavEHR / OMOP sources**

21491173 | Nefrodrain li Uit//ml; Nefrodrain re Uit//ml | measurement | n=15124 ; 3007123 | UrineSpontaan//ml | measurement | n=29366 ; 3014315 | UrineCAD//ml; UrineIncontinentie//ml; UrineSplint Li//ml; UrineSplint Re//ml; UrineSupraPubis//ml; UrineUP//ml | measurement | n=3319256 ; 3016267 | Spoelblaas Uit//ml | measurement | n=1290

**RICU / native AUMC reference sources**

8794 | UrineCAD | numericitems | n=1632547

**Technical finding**

All four unmatched WeavEHR urine OMOP sources show systematic 2x measurement multiplicity. After adjustment, a residual excess remains, reflecting additional urine-output sources beyond RICU UrineCAD.

**Medical review question**

Which additional AUMC urine-output sources should be included in the YAIB urine concept? In particular, should nephrostomy, suprapubic/splint/incontinence sources be included, and should bladder-irrigation output be excluded or treated separately because it may not represent true urine production?

**Reviewer decision**

- [ ] include
- [ ] exclude
- [ ] partial / conditional
- [ ] uncertain

**Reviewer notes / rationale**

_To be completed._

---
