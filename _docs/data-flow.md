# Data flow and decision rules

Three diagrams show how raw MEPS data becomes the modelling frame, and how the UK PMI framing is applied.
Each step names the `decisions.md` entry behind it. The diagrams show structure only. Counts of persons,
events and cost at each step are in the generated table at the end, so the numbers cannot drift from the
data.

## 1. Pipeline from raw MEPS files to the modelling frame

```mermaid
flowchart TD
    RAW["Raw MEPS files, 2022 and 2023<br/>full-year consolidated file<br/>inpatient, outpatient and office-based event files"]
    STG["Staging models stg_*<br/>loaded as published"]
    RAW --> STG

    STG --> CLEAN["int_person_clean<br/>reserved codes treated · age and region fallbacks<br/>see diagram 3"]
    STG --> EXPO["int_person_exposure<br/>months in eligible rounds / 12"]
    STG --> EVT["int_events_pmi<br/>PMI-scope flag and benefit type per event<br/>see diagram 2"]

    CLEAN --> POP{"Positive person weight?<br/>PERWT > 0"}
    EXPO --> POP
    POP -- "no" --> QUAR["quarantine_person<br/>not in person-level analytic population<br/>logged in exclusion_log"]
    POP -- "yes" --> RET["int_person_retained<br/>modelling population"]

    EVT --> CLM["int_person_claims<br/>claim count and cost per person-year<br/>ER-originated stays kept separately"]
    IDX["price_index_factor<br/>PCE-Health, BEA Table 2.5.4 line 37"] --> CLM

    RET --> MART["mart_person_year<br/>one row per person-year<br/>split: train · test · out_of_time"]
    CLM --> MART
    RET --> MARTB["mart_person_year_benefit<br/>one row per person-year per benefit type<br/>for the stacked candidate"]
    EVT --> MARTB

    MART --> GRP["Level grouping in the package<br/>see diagram 3"]
    GRP --> FRAME["Modelling frame<br/>train and test from 2022 · out-of-time from 2023"]
```

| Step | Decision log entry |
|---|---|
| Variable shortlist and mapping | 2026-10-31 MEPS variable shortlist and 2022-23 mapping (gate 1) |
| Reserved codes and age fallback | 2026-11-01 Reserved-code treatment (issue #12) |
| Region fallback and `left_survey_early` | 2026-11-01 Region for people who left part-way |
| Exposure | 2026-11-01 Exposure derivation (issue #13) |
| Modelling population | 2026-11-01 Modelling population and exclusions (gate 3) |
| PMI-scope claims | 2026-11-01 PMI-scope claim definition (gate 2) |
| On-levelling to 2023 prices | 2026-11-01 Price index for on-levelling (gate 4) and PMI-scope claim counts (issues #15, #16) |
| Train, test and out-of-time split | 2026-11-01 Household-grouped split within 2022 (issue #18) |
| Benefit types | 2026-11-02 Benefit types for the stacked candidate (issue #24) |
| Level grouping | Gate 6 (2026-11-02) |

## 2. Is an event a PMI-scope claim?

This is the UK framing. MEPS records all care. UK PMI pays only for part of it, because the NHS provides
the rest.

```mermaid
flowchart TD
    E["A MEPS event"] --> FILE{"Which event file?"}

    FILE -- "ER visit without admission ·<br/>prescribed medicine · dental ·<br/>vision · home health · other" --> OUTNHS["Out<br/>NHS-provided or not covered by PMI"]

    FILE -- "Inpatient stay" --> BIRTH{"Birth or pregnancy stay?<br/>RSNINHOS 4, 5 or 6"}
    BIRTH -- "yes" --> OUTMAT["Out<br/>maternity is usually excluded from UK PMI"]
    BIRTH -- "no" --> ER{"Began in the ER?<br/>EMERROOM = 1"}
    ER -- "yes" --> ERS["Out of claims<br/>UK emergency admissions are normally NHS<br/>kept as er_stay for the M5 sensitivity"]
    ER -- "no" --> INIP["In<br/>benefit type: inpatient and day-case"]

    FILE -- "Hospital outpatient or<br/>office-based visit" --> DOC{"Seen by a doctor?"}
    DOC -- "yes" --> SPEC{"Primary-care or unknown specialty?<br/>DRSPLTY_M18 6, 8, 14, 24, -7, -8"}
    SPEC -- "yes" --> OUTPC["Out<br/>NHS GP care"]
    SPEC -- "no" --> VC
    DOC -- "no" --> PT{"Physio or OT, psychologist<br/>or technician?<br/>MEDPTYPE_M18 10, 13 or 15"}
    PT -- "no" --> OUTNP["Out<br/>e.g. nurses, physician's assistants"]
    PT -- "yes" --> VC{"Excluded visit category?<br/>VSTCTGRY 1, 6, 7, 8, 9 or 10"}
    VC -- "yes" --> OUTVC["Out<br/>check-up · immunisation · vision exam ·<br/>pregnancy-related · well-child · laser eye"]
    VC -- "no" --> SURG{"Surgical procedure?<br/>SURGPROC = 1"}
    SURG -- "yes" --> INDC["In<br/>benefit type: inpatient and day-case"]
    SURG -- "no" --> INOP["In<br/>benefit type: outpatient"]
```

Psychiatry (specialty 28) and psychologist visits are in, including psychotherapy (visit category 4).
Session limits belong to the product layer, not the claim definition.

Known limitation: real UK PMI also excludes cover by condition (chronic conditions, and pre-existing
conditions under a moratorium). MEPS cannot model this cleanly, so the scope is defined by event type,
provider and visit category only.

## 3. How a raw value becomes a modelling level

### 3a. Person characteristics with fallbacks

```mermaid
flowchart TD
    AGE{"Year-end age valid?<br/>AGE22X or AGE23X"} -- "yes" --> AGEV["age, age_source = year_end"]
    AGE -- "no, person left part-way" --> AGEL["AGELAST<br/>age_source = last_eligible"]
    AGEV --> BANDS["Five-year age bands<br/>0–4 · 5–14 · 15–17 · 18–24 · 25–29 … 75–79 · 80+"]
    AGEL --> BANDS

    REG{"Year-end region valid?<br/>REGION22 or REGION23"} -- "yes" --> REGV["region, region_source = year_end"]
    REG -- "no, person left part-way" --> REGL["Latest round with a valid region<br/>region_source = last_round"]

    HS{"Health status valid in round 5/3?"} -- "yes" --> HSV["rthlth, mnhlth from 5/3"]
    HS -- "no" --> HSL["Latest round with a valid answer<br/>4/2, then 3/1, else null"]
```

### 3b. Answer levels for smoking, exercise and condition flags

```mermaid
flowchart TD
    V["A raw answer"] --> RC{"Reserved code?"}

    RC -- "no, a real answer" --> THIN{"Fewer than 30 claimants<br/>in this level?"}
    THIN -- "no" --> OWN["Own level"]
    THIN -- "yes" --> REF["Merged into the reference level<br/>reference = real answer with most exposure"]

    RC -- "-7, -8 or -15<br/>refused · don't know · cannot be computed" --> NULL["null"] --> REF

    RC -- "-1, not asked" --> QTYPE{"Adult-only question?<br/>smoking, exercise, nine condition flags"}
    QTYPE -- "yes" --> CHILD{"Under 18?"}
    CHILD -- "yes" --> NA["not_applicable"] --> REF
    CHILD -- "no" --> UNK["unknown<br/>adult never asked, often left part-way or died"]
    QTYPE -- "no, asked at any age<br/>ASTHDX, DIABDX_M18" --> UNK

    UNK --> WHICH{"Merging into the reference<br/>distorts its cost by more than 2%?"}
    WHICH -- "yes, e.g. smoking and exercise" --> CTRL["Kept as its own level in the fit<br/>as a control only, priced at the reference"]
    WHICH -- "no" --> REF
```

The `unknown` level is checked for leakage because it largely marks people who left the survey, often by
dying. An insurer cannot know this when pricing, so it is never priced as a rating factor.
`left_survey_early` is kept for analysis only and is never a rating factor.

## 4. Counts at each step

Generated, do not edit by hand. To be produced from `exclusion_log`, `int_events_pmi`, `int_person_claims`
and `mart_person_year`: persons, events and cost (nominal and at 2023 prices) for each year at each step
of diagrams 1 and 2.
