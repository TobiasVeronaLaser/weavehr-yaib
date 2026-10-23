# AUMC medical review: OMOP source candidates

> Values below are taken from generated WeavEHR concept outputs after WeavEHR normalization/transformation. They are not raw OMOP measurement rows. No patient identifiers or timestamps are included.

For each source, p05-p95 and representative quantile values are shown for clinical plausibility assessment. Min/max are retained to expose potential extreme or erroneous values.

## `ckmb` — creatine_kinase_MB

**Technical summary:** No OMOP multiplicity effect detected. WeavEHR OMOP concept 3005785 contains far more observations than the RICU reference item, indicating a substantial source-coverage difference.

**Review question:** Is AUMC OMOP concept 3005785 (MB-Massa / CK-MB mass) clinically equivalent to the RICU CK-MB concept and appropriate for inclusion?

**RICU reference source(s)**

- `6824` — CK-MB (numericitems, n=2,315)

**WeavEHR / OMOP candidate source(s)**

- `3005785` — **MB-Massa (bloed)//µg/l**
  - normalized concept/unit: `creatine_kinase_MB//ng/mL`
  - n=59,014; p05=3.1; q25=8.9; median=17.9; q75=32.4; p95=162
  - representative values: 3.1 | 8.9 | 17.9 | 32.4 | 162
  - observed extremes: min=0, max=2227

**Reviewer decision:**

**Reviewer notes:**

## `methb` — methemoglobin

**Technical summary:** No OMOP multiplicity effect detected. WeavEHR includes a substantially larger Met-Hb/FMetHb source population than the RICU reference.

**Review question:** Should all Met-Hb/FMetHb source variants represented by OMOP concept 3007930 be included in the YAIB methemoglobin concept?

**RICU reference source(s)**

- `11692` — Met-Hb (bloed) (numericitems, n=2,714)

**WeavEHR / OMOP candidate source(s)**

- `3007930` — **FMetHb//None; Met-Hb  (bloed)//Geen; Met-Hb (bloed)//Geen**
  - normalized concept/unit: `methemoglobin//%`
  - n=336,872; p05=0.2; q25=0.6; median=0.8; q75=1.1; p95=1.5
  - representative values: 0.2 | 0.6 | 0.8 | 1.1 | 1.5
  - observed extremes: min=-1.2, max=29.2

**Reviewer decision:**

**Reviewer notes:**

## `lymph` — lymphocytes

**Technical summary:** WeavEHR and RICU use different lymphocyte source combinations. RICU includes both percentage and other lymphocyte items; WeavEHR maps them differently into OMOP concept 3002030.

**Review question:** Which AUMC lymphocyte measurements belong in the YAIB lymph concept, especially percentage versus non-percentage variants?

**RICU reference source(s)**

- `14258` — Lymfocyten (bloed) (numericitems, n=11,647)
- `11846` — Lymfocyten % (bloed) (numericitems, n=4,606)

**WeavEHR / OMOP candidate source(s)**

- `3002030` — **Lymfocyten % (bloed)//Geen; Lymfocyten//None**
  - normalized concept/unit: `lymphocytes//%`
  - n=4,654; p05=2; q25=6; median=13; q75=23; p95=35
  - representative values: 2 | 6 | 13 | 23 | 35
  - observed extremes: min=0, max=100

**Reviewer decision:**

**Reviewer notes:**

## `mchc` — mean_corpuscular_hemoglobin_concentration

**Technical summary:** No OMOP multiplicity effect detected. WeavEHR includes additional MCHC source variants, including LabZis2/M.C.H.C., beyond the RICU item.

**Review question:** Are the additional MCHC variants (including LabZis2 and M.C.H.C.) clinically equivalent and appropriate for inclusion?

**RICU reference source(s)**

- `18666` — MCHC (bloed) (numericitems, n=2,686)

**WeavEHR / OMOP candidate source(s)**

- `40762530` — **M.C.H.C.//mmol/l; MCHC (bloed)-LabZis2//mmol/cel; MCHC (bloed)//mmol/cel**
  - normalized concept/unit: `mean_corpuscular_hemoglobin_concentration//%`
  - n=8,010; p05=32.22; q25=33.831; median=33.831; q75=35.442; p95=37.053
  - representative values: 32.22 | 33.831 | 33.831 | 35.442 | 37.053
  - observed extremes: min=25.776, max=3230.05

**Reviewer decision:**

**Reviewer notes:**

## `ptt` — partial_thromboplastin_time

**Technical summary:** No OMOP multiplicity effect detected. WeavEHR includes substantially more APTT/Cephaline-related observations than RICU.

**Review question:** Should all APTT / CEF-KAOL.T / Cephalinetyd source variants be treated as equivalent for the YAIB ptt concept?

**RICU reference source(s)**

- `17982` — APTT (bloed) (numericitems, n=68,230)

**WeavEHR / OMOP candidate source(s)**

- `3013466` — **APTT  (bloed)//sec; APTT (bloed)//sec; CEF-KAOL.T (bloed)//sec; Cephalinetyd//sec**
  - normalized concept/unit: `partial_thromboplastin_time//sec`
  - n=204,872; p05=31; q25=37; median=45; q75=60; p95=90
  - representative values: 31 | 37 | 45 | 60 | 90
  - observed extremes: min=0, max=241

**Reviewer decision:**

**Reviewer notes:**

## `inr_pt` — prothrombin_time_international_normalized_ratio

**Technical summary:** OMOP concept 3032080 shows systematic 2x source multiplicity, but a large residual excess remains after adjustment. WeavEHR includes substantially more prothrombin/INR observations than RICU.

**Review question:** Are all AUMC prothrombin-time/INR source variants mapped to OMOP concept 3032080 clinically appropriate for the YAIB inr_pt concept?

**RICU reference source(s)**

- `11893` — Prothrombinetijd (bloed) (numericitems, n=66,847)

**WeavEHR / OMOP candidate source(s)**

- `3032080` — **Prothrombinetijd  (bloed)//INR; Prothrombinetijd (bloed)//INR**
  - normalized concept/unit: `prothrombin_time_international_normalized_ratio//None`
  - n=387,380; p05=1; q25=1.13; median=1.26; q75=1.47; p95=2.35
  - representative values: 1 | 1.13 | 1.26 | 1.47 | 2.35
  - observed extremes: min=0, max=159

**Reviewer decision:**

**Reviewer notes:**

## `cl` — chloride

**Technical summary:** WeavEHR includes a large additional chloride source group (Chloor Astrup / Cl onv.ISE) beyond the RICU chloride item.

**Review question:** Should blood-gas/Astrup/ISE chloride measurements be pooled with standard laboratory chloride for the YAIB cl concept?

**RICU reference source(s)**

- `9930` — Chloor (bloed) (numericitems, n=178,659)

**WeavEHR / OMOP candidate source(s)**

- `3014576` — **Chloor (bloed)//mmol/l; Chloor//mmol/l**
  - normalized concept/unit: `chloride//mEq/L`
  - n=180,102; p05=97; q25=103; median=108; q75=113; p95=120
  - representative values: 97 | 103 | 108 | 113 | 120
  - observed extremes: min=-103, max=11010
- `3018572` — **Chloor Astrup//mmol/l; Cl (onv.ISE) (bloed)//mmol/l**
  - normalized concept/unit: `chloride//mEq/L`
  - n=346,818; p05=96; q25=102; median=106; q75=110; p95=116
  - representative values: 96 | 102 | 106 | 110 | 116
  - observed extremes: min=0, max=200

**Reviewer decision:**

**Reviewer notes:**

## `temp` — temperature

**Technical summary:** WeavEHR includes blood temperature plus rectal, axillary, ear and oral temperature sources, while RICU is narrower.

**Review question:** Which temperature measurement sites should be included in the YAIB temp concept?

**RICU reference source(s)**

- `8658` — Temp Bloed (numericitems, n=1,999,754)

**WeavEHR / OMOP candidate source(s)**

- `3006322` — **Temp Oraal//°C**
  - normalized concept/unit: `temperature//C`
  - n=546; p05=31.8; q25=32.8; median=34.7; q75=36.5; p95=38
  - representative values: 31.8 | 32.8 | 34.7 | 36.5 | 38
  - observed extremes: min=31, max=39.3
- `3022060` — **Temp Rectaal//°C**
  - normalized concept/unit: `temperature//C`
  - n=387,259; p05=32.4; q25=35.7; median=36.8; q75=37.6; p95=38.8
  - representative values: 32.4 | 35.7 | 36.8 | 37.6 | 38.8
  - observed extremes: min=0, max=373
- `3025085` — **Temp Axillair//°C**
  - normalized concept/unit: `temperature//C`
  - n=202,198; p05=35.4; q25=36.2; median=36.8; q75=37.3; p95=38.3
  - representative values: 35.4 | 36.2 | 36.8 | 37.3 | 38.3
  - observed extremes: min=-543, max=376.5
- `3025163` — **Temp Oor//°C**
  - normalized concept/unit: `temperature//C`
  - n=52,540; p05=35.9; q25=36.6; median=37.1; q75=37.6; p95=38.5
  - representative values: 35.9 | 36.6 | 37.1 | 37.6 | 38.5
  - observed extremes: min=0, max=365
- `21490586` — **PiCCO Tb blood temperature//°C; Temp Bloed//°C**
  - normalized concept/unit: `temperature//C`
  - n=2,004,487; p05=35.6; q25=36.3; median=36.8; q75=37.1; p95=37.7
  - representative values: 35.6 | 36.3 | 36.8 | 37.1 | 37.7
  - observed extremes: min=0, max=371

**Reviewer decision:**

**Reviewer notes:**

## `fio2` — fraction_of_inspired_oxygen

**Technical summary:** Main oxygen concentration source closely matches RICU, but WeavEHR additionally includes O2 Volume source variants.

**Review question:** Does the AUMC O2 Volume source represent FiO2 sufficiently to be included in the YAIB fio2 concept?

**RICU reference source(s)**

- `12279` — O2 concentratie (numericitems, n=15,645,395)

**WeavEHR / OMOP candidate source(s)**

- `3020716` — **O2 Volume(2)//None; O2 Volume//None**
  - normalized concept/unit: `fraction_of_inspired_oxygen//%`
  - n=85,391; p05=38; q25=40; median=41; q75=46; p95=61
  - representative values: 38 | 40 | 41 | 46 | 61
  - observed extremes: min=0, max=100
- `3025408` — **O2 concentratie//Geen; Zephyros O2i//Geen**
  - normalized concept/unit: `fraction_of_inspired_oxygen//%`
  - n=15,645,447; p05=29; q25=36; median=41; q75=50; p95=65
  - representative values: 29 | 36 | 41 | 50 | 65
  - observed extremes: min=0, max=2.39387e+06

**Reviewer decision:**

**Reviewer notes:**

## `urine` — urine_output

**Technical summary:** All four unmatched WeavEHR urine OMOP sources show systematic 2x measurement multiplicity. After adjustment, a residual excess remains, reflecting additional urine-output sources beyond RICU UrineCAD.

**Review question:** Which additional AUMC urine-output sources should be included in the YAIB urine concept? In particular, should nephrostomy, suprapubic/splint/incontinence sources be included, and should bladder-irrigation output be excluded or treated separately because it may not represent true urine production?

**RICU reference source(s)**

- `8794` — UrineCAD (numericitems, n=1,632,547)

**WeavEHR / OMOP candidate source(s)**

- `3007123` — **UrineSpontaan//ml**
  - normalized concept/unit: `urine_output//mL`
  - n=29,366; p05=20; q25=100; median=200; q75=350; p95=600
  - representative values: 20 | 100 | 200 | 350 | 600
  - observed extremes: min=0, max=2000
- `3014315` — **UrineCAD//ml; UrineIncontinentie//ml; UrineSplint Li//ml; UrineSplint Re//ml; UrineSupraPubis//ml; UrineUP//ml**
  - normalized concept/unit: `urine_output//mL`
  - n=3,319,256; p05=18; q25=60; median=100; q75=175; p95=370
  - representative values: 18 | 60 | 100 | 175 | 370
  - observed extremes: min=-20, max=6.35241e+06
- `3016267` — **Spoelblaas Uit//ml**
  - normalized concept/unit: `urine_output//mL`
  - n=1,290; p05=0; q25=200; median=540; q75=3000; p95=4200
  - representative values: 0 | 200 | 540 | 3000 | 4200
  - observed extremes: min=0, max=14000
- `21491173` — **Nefrodrain li Uit//ml; Nefrodrain re Uit//ml**
  - normalized concept/unit: `urine_output//mL`
  - n=15,124; p05=0; q25=15; median=40; q75=85; p95=220
  - representative values: 0 | 15 | 40 | 85 | 220
  - observed extremes: min=0, max=1200

**Reviewer decision:**

**Reviewer notes:**
