# Decision log

Format: date, decision, why, alternatives considered. Newest at the bottom.

## 2026-10-31 Data source is MEPS
Decision: US MEPS Household Component Full-Year Consolidated files plus event files.
Why: it is the only free person-level dataset with exposure, utilisation, paid costs and risk characteristics.
Alternatives: UK CPRD+HES (licence and fees), CPRD synthetic (no costs), NHS artificial HES (not
statistically realistic), CMS Marketplace PUFs (filed premiums, not claims), freMTPL2 (not health).

## 2026-10-31 Time periods and validation design
Decision: fit on 2022, validate out-of-time on 2023, and make the final refit on 2022+2023 pooled with a year
term. Add 2019 only if claimant counts are thin. Exclude 2020-21 because of COVID. Split within-year
hold-outs by household (`DUID`), because households appear in both survey years.
Why: validation goes forward in time, as in real pricing. Grouping by household avoids leakage.

## 2026-10-31 Trend
Decision: on-level severity with the price index AHRQ recommends for MEPS expenditure (confirm in M1).
Estimate frequency trend from the data (year term). State the assumptions and show low and high sensitivity.

## 2026-11-01 Price index for on-levelling and projection (decision gate 4, part 1, confirmed)
Decision: use the Personal Consumption Expenditure Health index (PCE-Health, Bureau of Economic
Analysis). Confirmed by the user 2026-11-01. See `_docs/price-index.md` for the full evidence.
Why: AHRQ's own price index page recommends PCE-Health or the Personal Health Care Index (PHC)
specifically for projecting an expenditure estimate from one year to another, which is our
on-levelling and rating-period projection use case. Two AI summaries of that page disagreed with
each other (one said GDP, one said PHC/PCE-Health), so the page was downloaded and read directly
rather than trusting either summary, since this is a decision gate. PCE-Health is picked over PHC
only because it is a single public BEA table, PHC needs a CMS zip file.
Alternatives: GDP price index, rejected, that is AHRQ's recommendation for a different objective
(broad macro expenditure-level comparisons). CPI-M, rejected, AHRQ says it only reflects
out-of-pocket expenses. PHC, a valid equal alternative, not used only for convenience. A custom
blend of PHC service-type components, noted as a possible refinement, not pursued for M1/M2.

## 2026-10-31 UK framing
Decision:
- PMI-scope claims only (inpatient/day-case, hospital outpatient/specialist, diagnostics)
- Report relativities rather than dollar levels
- Simulated UK product layer (excess, outpatient limit, underwriting type)
- Sex excluded from the final rating structure, and no race, income or education as rating factors
- Models fitted unweighted on exposure, with the survey weight `PERWT23F` used only for population sanity checks

## 2026-10-31 Code structure
Decision: notebooks for explanation, an installable package for all reusable logic, and versioned
aggregated output tables forming the contract for Phase 2 (plan section 6).

## 2026-10-31 MEPS variable shortlist and 2022-23 mapping (decision gate 1)
Decision: the shortlist and name mapping in `_docs/variable-mapping.md` is approved, with these
specific calls.
- BMI (`ADBMI42`) is excluded from the pooled 2022+2023 model and the final rating structure. A
  2022-only BMI sensitivity analysis is moved to the stretch goals (plan section 5), not MVP.
- `OFTSMK53` (main interview, all adults, present in both years) is the primary smoking rating
  factor. `ADSMOK42` (SAQ) is kept only as a 2023-only consistency check against it, because it
  does not exist in the 2022 file at all, corrected at QA from an earlier claim that it was in
  both years.
- `PHYEXE53` (moderate/vigorous exercise 5x a week) is confirmed present in both years and added
  as a candidate lifestyle factor.
- Service-category expenditure variables (`IPTEXP`, `OPTEXP`, `OBVEXP`, `OBDRV`, `OBDEXP`,
  `ERTEXP`, `RXEXP`, both years) are added to the shortlist, because they cost the PMI-scope
  claim categories directly from the FYC file.
Why:
- `ADBMI42` and `CHBMIX42` exist in the 2022 Full-Year Consolidated file (HC-243) but no BMI
  variable exists in the 2023 file (HC-251) under any name or round suffix, confirmed by grepping
  both years' raw SAS program statement files. A factor absent from 2023 cannot be checked on the
  out-of-time test (plan section 2.5), which is the main reason to exclude it, not only that it
  would distort the pooled fit.
- An earlier version of this decision misread the `_M18` suffix on `DIABDX_M18` as an age-18+
  restriction. AHRQ's own documentation defines `_Myy` as marking the collection year a variable's
  definition changed, so `_M18` means "changed in collection year 2018", corrected after the user
  challenged it and a label comparison confirmed `DIABDX_M18` has no "(>17)" age qualifier unlike
  every other condition flag in the shortlist. No decision changes as a result. `DIABDX_M18` is
  still used as-is, but the mapping note is corrected.
- Adult-only condition flags (`HIBPDX`, `CHDDX`, `ANGIDX`, `MIDX`, `OHRTDX`, `STRKDX`, `CHOLDX`,
  `CANCERDX`, `ARTHDX`) are coded `-1 = INAPPLICABLE` for children, since the question is age
  restricted. M2 must set an explicit coding rule for this, not decided here.
Alternatives: checking a separate 2023 PUF (such as Preventive Care) for a BMI variable, rejected
for now, can be revisited as a stretch goal if time allows.

## 2026-11-01 Office-based events can be split by provider specialty
Decision: office-based events do not need a proxy for the PMI-scope claim decision (decision gate
2). `DRSPLTY_M18` (doctor's specialty) and `VSTCTGRY` (visit category) are both available in the
office-based event file, confirmed in both 2022 (HC-239G) and 2023 (HC-248G).
Why: grepped both years' raw SAS program statement files directly for the office-based event
file. Both years carry identical variables and identical coded-value lists, e.g. `DRSPLTY_M18`
runs from allergy/immunology through general practice, orthopedics, psychiatry and more, and
`VSTCTGRY` covers general checkup, diagnosis/treatment, emergency, psychotherapy, follow-up,
immunisations, vision exam, pregnancy-related, well-child and other. This resolves issue #5 and
removes "event-file specialty split may not exist" from the open risks (`_docs/plan.md` section
5), because the specialty split does exist.
Alternatives: none needed, the specialty and visit-category fields were found on first check.

## 2026-11-01 PMI-scope claim definition (decision gate 2, approved)
Decision: a PMI-scope claim is an event that meets the rule for its file. The evidence, tables and the
level by level lists are in `_docs/pmi-scope.md`, and the rules are implemented once in
`src/health_pricing/evidence/pmi_scope.py`.
- **Inpatient.** All stays except birth and pregnancy stays (`RSNINHOS` 4, 5, 6) and stays that began
  in the emergency room (`EMERROOM` = 1). ER-originated stays are flagged, not dropped from the data.
- **Hospital outpatient and office-based, one rule for both.** The provider must qualify and the visit
  category must not be excluded.
  - Doctors qualify unless `DRSPLTY_M18` is 6 (family practice), 8 (general practice), 14 (internal
    medicine), 24 (paediatrician) or unknown (-8, -7).
  - Non-physicians qualify only if `MEDPTYPE_M18` is 10 (physical or occupational therapist), 13
    (psychologist) or 15 (technician). Nurses (8) and every other type are out, because MEPS has no
    specialist-nurse category.
  - `VSTCTGRY` 1, 6, 7, 8, 9 and 10 (general checkup, immunisations, vision exam, pregnancy-related,
    well-child exam, laser eye surgery) are out.
- **Psychiatric care.** Psychiatry (specialty 28) and psychologist visits are in, including visit
  category 4 (psychotherapy). Mental health limits belong to the product layer.
- **Everything else is out.** ER events not followed by admission, prescribed medicines, dental, vision,
  home health and other medical spending.
- **Cost.** The event expenditure variable (`IPXP`, `OPXP`, `OBXP`).
What it captures with ER-originated stays out: 27.5% (2022) and 29.6% (2023) of total spending, 49.1% and
51.4% of the cost of the three event files, and 40.4% (9,073 of 22,431) and 41.8% (7,907 of 18,919) of
persons with a claim. With them included (the M5 sensitivity), the shares are 36.4% and 39.3% of total
spending, 65.1% and 68.3% of the event files, and 41.5% and 43.0% of persons.
Why:
- Hospital outpatient was blanket "in" in the starting position. The evidence showed 28.5% (2022) and
  29.3% (2023) of outpatient cost fails the same specialty and visit rules, mainly general checkups,
  primary-care specialties, nurses and physician's assistants. The user approved applying the office-based
  rules to both files.
- Technicians are in for both files, because diagnostics are covered by PMI. The first proposal's
  outpatient argument wrongly named technicians. It was corrected before approval.
- Stays that began in the ER are out because UK emergency admissions are normally NHS and PMI generally
  covers elective care. This overrides the "an admission that follows still counts as inpatient" note in
  plan section 2.4.1. They were 51.0% (2022) and 45.4% (2023) of inpatient cost.
- Birth and pregnancy stays are 7.3% and 6.4% of inpatient cost, and UK PMI usually excludes maternity.
- Physiotherapy, occupational therapy and psychology are in because UK PMI covers them. Session limits
  are handled later in the product layer, not in the claim definition.
Alternatives: counting ER-originated stays (kept as an M5 sensitivity), treating all hospital outpatient
as in (rejected on the evidence above), excluding all non-physicians (would cut the captured share to
21.2% and 23.4% of total spending), and excluding psychotherapy visits (small effect, about one point).
Consequence for issue #15: the per-person claim table keeps a count and cost of ER-originated stays, so
the M5 sensitivity needs no rebuild.

## 2026-11-01 Loader correction (found in M2 task #8)
Decision: when a fixed-width numeric field contains a literal decimal point, the loader keeps the value
as written and applies the SAS implied decimals only when there is no point.
Why: AHRQ stores event costs and weights with literal points. The M1 loader divided them again by
10^decimals, so event costs were 100 times and weights 10^6 times too small. After the fix, event-file
totals agree with the FYC category totals to within 0.01% and the weights sum to about 333 million.
Alternatives: none. The earlier behaviour was a bug. Regression tests were added in `tests/test_sas_layout.py`
and `tests/test_load.py`.

## 2026-11-01 Reserved-code treatment (issue #12) and AGELAST added to the shortlist
Decision: the cleaned person model `int_person_clean` (one row per person-year, both years) treats
reserved codes as follows. The value rules after treatment are in `dbt/models/intermediate/schema.yml`.
- **Shortlist change (gate 1, approved by the user).** `AGELAST` is added to the shortlist. It has the same
  name in both years.
- **Age.** `age` is the year-end age (`AGE22X`, `AGE23X`) where valid, else `AGELAST`. `age_source` says
  which (`year_end` or `last_eligible`). 195 people in 2022 and 148 in 2023 have no year-end age because
  they left the survey part-way through the year, and all of them get an age from `AGELAST`. For the
  22,236 (2022) and 18,771 (2023) people who have both, the two agree for 100.0% and 99.9%. In 2023, 14
  differ by one year. Age 85 is kept and `age_topcoded` flags it.
- **`-1` on adult-only questions** (`OFTSMK53`, `PHYEXE53` and the nine condition flags `HIBPDX`, `CHDDX`,
  `ANGIDX`, `MIDX`, `OHRTDX`, `STRKDX`, `CHOLDX`, `CANCERDX`, `ARTHDX`). `-1` for a person under 18 is
  `not_applicable`. `-1` for an adult is `unknown`, a separate level. The user approved this change to the
  first proposal, which would have treated all adult `-1` codes as missing.
- **`-1` on `ASTHDX` and `DIABDX_M18`**, which are asked at any age, is `unknown` for everyone.
- **`-7`, `-8`, `-15`** become null on every treated variable. `-1` on `SEX`, `region`, `inscov` and
  `ASSTIL31` becomes null. `-15` on the five visit and discharge counts becomes null.
- **Levels** are text, so the levels sit together. Yes/no questions use `'1'` (yes), `'0'` (no),
  `not_applicable` and `unknown`. `OFTSMK53` uses `'1'` (every day), `'2'` (some days), `'3'` (not at
  all), `not_applicable` and `unknown`. Smoking and exercise are adult-only questions, so the children
  rule applies to them as well. The issue named only the nine flags.
- **Health status.** `rthlth` and `mnhlth` take the latest round with a valid answer (5/3, then 4/2, then
  3/1), with the round in `rthlth_round` and `mnhlth_round`. 84 people (2022) and 60 (2023) have no valid
  `rthlth` in any round, and 88 and 59 have no valid `mnhlth`. They stay null.
- **Round dates and eligibility** (`BEGRF*`, `ENDRF*`, `ELGRND*`) keep `-1`, which means "not in that
  round" and feeds the exposure measure in #13. Their `-7`, `-8` and `-15` become null.
Why:
- The adult `unknown` level is not noise. It marks adults who were never asked, for example people who
  left before round 5/3 or died before the priority-conditions section. The table shows the cost is
  concentrated, so the level may act as a leaver or death indicator. It is checked for leakage in M3
  before it can enter a rating structure.
- Using `AGELAST` keeps people who left part-way, who carry 2.4% (2022) and 2.3% (2023) of total spending,
  instead of dropping them, and avoids a gate 3 exclusion of more than 1% of cost.
Adults at the `unknown` level, per variable (the full table is `uv run python -m
health_pricing.evidence.clean_checks`):

| Variable | 2022 | 2023 |
|---|---|---|
| `OFTSMK53` and `PHYEXE53` | 253 (1.4% of adults, 3.8% of cost) | 209 (1.4% of adults, 4.2% of cost) |
| The nine adult-only condition flags (each) | 175 (1.0% of adults, 0.4% of cost) | 134 (0.9% of adults, 0.5% of cost) |
| `ASTHDX` and `DIABDX_M18` (each) | 67 (0.4% of adults, 0.2% of cost) | 55 (0.4% of adults, 0.4% of cost) |

Alternatives: dropping people with no year-end age (rejected, 2.3% of cost), treating adult `-1` as null
(rejected by the user, it hides the leaver signal), keeping children's `-1` as null instead of
`not_applicable` (rejected, it would mix children with adults who were not asked).

## 2026-11-01 Exposure derivation (issue #13)
Decision: `int_person_exposure` gives each person-year an exposure in years, at month resolution. A
calendar month counts when it lies inside the reference period of a round in which the person is
eligible (`ELGRND` = 1), using `BEGRFM`, `BEGRFY`, `ENDRFM` and `ENDRFY` for rounds 3/1, 4/2 and 5/3.
- A reference period that starts before the year counts from January, and one that ends after the year
  counts to December. Months shared by two rounds count once.
- A round in which the person is not in a household unit (`ELGRND` = 4) adds no months, so people with a
  gap (181 in 2023 were eligible in rounds 3/1 and 5/3 only) get fewer months.
- The combined year-level `ENDRFM`/`ENDRFY`/`ELGRND` are kept in `int_person_clean` only as a cross-check.
- `exposure` = months in scope / 12, so it lies in [0, 1]. A partly covered month counts in full, because
  the file has no day-level dates.
Why:
- Months are the finest resolution available. The combined `ENDRFM22`/`ENDRFM23` alone would ignore gaps
  and late entry (births and new members start in months 2 to 11 of the year).
- Every person has at least one eligible round with valid dates in both years, so no person has zero or
  null exposure. 21,740 of 22,431 (2022) and 18,394 of 18,919 (2023) have the full 12 months.
- Zero-weight persons still get an exposure from their rounds. Whether to keep them is the gate 3
  decision in #14, not an exposure question.
Alternatives: using only the year-end reference period `ENDRFM`/`ENDRFY` (ignores gaps and late entry),
using `PERWT` or person-time from the weight (the weight is a survey weight, not exposure), and counting
partial months as half months (no day information to support it).

## 2026-11-01 Modelling population and exclusions (issue #14, decision gate 3)
Decision: the modelling population is person-years with a positive person weight. Persons with `PERWT` = 0
are moved to quarantine with the reason code `not_in_person_level_analytic_population` (text: "not in
person-level analytic population"). This is a definition of the modelling population, not a data-quality
exclusion. The user approved it on 2026-11-01.
- 684 of 22,431 persons in 2022 (3.0%, 1.3% of `TOTEXP`) and 456 of 18,919 in 2023 (2.4%, 1.1% of
  `TOTEXP`) are quarantined. The modelling population is 21,747 (2022) and 18,463 (2023) person-years.
- The other rules found nothing in either year. They are no duplicate `DUPERSID` within a year, no
  missing age, sex, region or coverage, no zero or null exposure and no negative expenditure.
- `exclusion_log` lists every rule by year with persons flagged, persons quarantined and the shares of
  persons and `TOTEXP`. `dbt/tests/exclusions_above_1_percent_are_decided.sql` fails if a rule over 1%
  has no recorded decision, and `retained_plus_quarantined_equals_raw_persons.sql` checks that no
  person-year is lost.
- 8,284 people appear in both years, out of 33,066 distinct people in 41,350 person-years. Within-year
  splits are grouped by household (see the 2026-10-31 time periods decision).
Why:
- Zero weight is AHRQ's marker for people outside the surveyed population or without a full response.
  They average 0.79 years of exposure against 0.99, a cost of about 3,200 to 3,800 against 7,800 to
  8,500, and about 40% have no spending or visits. Their records are less complete, so keeping them would
  dilute frequency and exposure.
- Weights are used only for sanity checks, so this does not change the reconciliation in #19.
Alternatives: keeping them (rejected, incomplete records), and treating the rule as a data-quality
exclusion (rejected by the user, because the rule defines the population).

## 2026-11-01 Region for people who left part-way, and the pre-approved pattern (follow-up under #14)
Decision: `REGION31`, `REGION42` and `REGION53` are added to the shortlist (gate 1, approved by the user).
`region` is the year-end region where valid, else the latest round with a valid region, with `region_source`
(`year_end` or `last_round`). It affects 195 people in 2022 and 148 in 2023, and none are left without a
region. Seven people in each year are also zero-weight, so 188 (2022) and 141 (2023) region-filled people
remain in the modelling population. The #9, #10 and #12 tests and rules were updated and pass.
- **Pre-approved pattern, for the future with no gate needed.** A person-level characteristic whose
  year-end value is -1 because the person left part-way takes the latest valid round value plus a `_source`
  flag. A question asked in the last round only keeps an `unknown` level instead. This is recorded in
  `AGENTS.md`.
- **`left_survey_early`** (true when the person was no longer eligible at the end of the year, `ELGRND` = 3)
  marks those people for analysis only. It must never be used as a rating factor. It equals
  `age_source = 'last_eligible'` in both years.
Why: the 343 people carry about 2.3% to 2.4% of total spending, and region is a rating factor. About 1% of
people moved during the year, so the latest round is a small approximation.
Alternatives: an `unknown` region level (rejected, it would act as a leaver indicator) and excluding
them (rejected, over 1% of cost).

## 2026-11-01 PMI-scope claim counts and on-levelled costs (issues #15 and #16)
Decision: `int_person_claims` gives each person-year a claim count and cost under the approved definition.
A claim is one in-scope event record, and its cost is the event expenditure (`IPXP`, `OPXP`, `OBXP`). People
with no in-scope events stay in with zeros. Inpatient stays that began in the emergency room, and were not
birth related, are kept in `er_stay_count` and `er_stay_cost` and are not in `claim_count` or `claim_cost`,
so the M5 sensitivity needs no rebuild.
- Costs are on-levelled to 2023 prices with PCE-Health: factor = 113.121 / 110.256 = 1.02599 (BEA Table
  2.5.4 line 37, annual averages, downloaded 2026-11-01). 2022 costs are multiplied by it and 2023 costs
  are unchanged. Both the nominal and on-levelled costs are kept.
- Event-file totals agree with the FYC category totals (`IPTEXP`, `OPTEXP`, `OBVEXP`) to within 0.001%
  in every year and event type, so the 1% tolerance is not close to being used.
- Event costs carry cents and `TOTEXP` is rounded to whole dollars, so 64 people have a claim cost above
  `TOTEXP` by less than one dollar (the largest is 0.87). The check allows less than one dollar.
Why: counting event records matches the frequency model's unit, and keeping the emergency room stays
separate lets the M5 sensitivity add them back without re-running the claim logic.
Alternatives: counting visits per person-day (the files do not give a stable day key), and dropping the
emergency room stays from the data (rejected, the sensitivity needs them).

## 2026-11-01 Modelling table and rating factor candidates (issue #17)
Decision: `mart_person_year` is the modelling table, one row per person-year in the modelling population
(`int_person_retained` joined to `int_person_claims`). Column roles are declared in
`dbt/models/marts/schema.yml` and tested in `tests/test_mart.py`.
- **Rating factor candidates** are `age`, `region`, `inscov`, `rthlth`, `mnhlth`, `OFTSMK53`, `PHYEXE53` and
  the 11 condition flags. This is a candidate list from the approved shortlist, not the final rating
  structure. Which of them are permitted UK rating factors, and how levels are grouped, are decided at
  gates 6 and 7.
- **Analysis only:** `SEX`, `age_source`, `age_topcoded`, `region_source`, `left_survey_early`, `VARSTR`,
  `VARPSU` and the `er_stay` columns. Sex and `left_survey_early` must never be rating factors.
- Race, income, education and poverty variables are not in the table.
Why: a declared role for every column lets a test stop a column such as sex or the leaver flag drifting
into the rating structure.

## 2026-11-01 Household-grouped split within 2022 (issue #18)
Decision: the `split` column in `mart_person_year` takes `train`, `test` or `out_of_time`. Every 2023 row is
`out_of_time`. A 2022 household (`DUID`) is `train` if the first 8 hex digits of `md5(DUID || '|split-v1')`,
read as a number modulo 100, are below 80, and `test` otherwise. There is no random state, so the split is
the same on every run and machine. The rule is the dbt macro `household_split` and an independent Python copy
in `tests/test_split.py` checks that they agree.
- 2022 shares: 80.9% of persons and 79.6% of claim cost are train, 19.1% and 20.4% are test (targets 80 and
  20, each within 2 points). 8,566 train and 2,090 test households.
- 4,005 of the 15,565 households appear in both years, and 8,109 people appear in both years after the
  exclusions (8,284 before them). This is the same-people overlap stated in the 2026-10-31 time periods
  decision. It is acceptable for the out-of-time test because households
  stay in MEPS for two years and renew like policyholders, and the within-year split is grouped by
  household so no household is on both sides of it.
Why: grouping by household stops leakage between family members. The salt `split-v1` was the first one tried
and met the 2 point tolerance, so no other salt was tried.
Alternatives: a random split by person (leaks within households), and a seeded random generator (a hash is
simpler and has nothing to seed).

## 2026-11-01 Reconciliation to published figures (issue #19)
Decision: the data layer is reconciled to AHRQ's published person counts, weighted population, the 2022
weighted mean total expenditure ($6,765, Statistical Brief #560) and the `TOTEXP` band counts in both
codebooks. All match (`_docs/reconciliation.md`). No published 2023 mean total expenditure per person was
found, so 2023 is checked by the five `TOTEXP` bands (unweighted and weighted, all equal) and the computed
2023 mean of $7,487.26 is recorded as "computed, no published figure". The user accepted this on 2026-11-01.
Why: a remembered or computed number is not a published figure, and the band check covers the whole weighted
expenditure distribution for 2023. Alternative: the user downloading the mean from AHRQ's dashboard
(declined as unnecessary).


## 2026-11-02 M3 model structure is decided by comparison, and the benefit-type and multiplicative-structure approach
Decision (user, 2026-11-02): the M3 model structure is not assumed. Up to four candidates predict the same
quantity, expected annual PMI-scope cost per person-year at 2023 prices, and are scored on the 2022
household-grouped holdout with the same package code. The final choice is a decision gate (issue #32).
- **(a)** binomial GLM with a cloglog link on the claimant indicator, with a `log(exposure)` offset, and Gamma
  log-link severity on annual cost per claimant with weight 1.
- **(b)** as (a), but Poisson on the claimant indicator.
- **(c)** stacked by benefit type (inpatient and day-case versus outpatient), with a `benefit_type` x age
  interaction tested by likelihood-ratio test.
- **(d)** optional, event-based Poisson or negative binomial, with Gamma on average cost per event weighted by
  event count.
- Claim count is part of the outcome and unknown at quote time, so in (a) to (c) it is never a weight or a
  predictor. Event count is a weight only in (d).
- Yardstick: Tweedie deviance on annual cost (p = 1.5, checked at 1.3 and 1.7), Gini, lift, double-lift, and A/E
  by factor and by predicted-cost decile. Family-specific checks are supporting evidence only.
- **Benefit types for (c).** Inpatient and day-case versus outpatient. Outpatient and office-based events with
  `SURGPROC` = 1 (surgical procedure performed on the visit) count as day-case. If the flag proves unusable the
  split stays simple and the limitation is logged (issue #24).
- **Large claims.** The cap applies per person-year, so `mart_person_year` does not change (issue #27).
- **Multiplicative pricing.** The departure from a product of relativities is reported in #32 for information
  only, and the risk model is chosen on the common yardstick. If the chosen structure is not exactly
  multiplicative, an M6 task (#37) fits a log-link GLM to its predicted annual cost, reports the approximation
  error overall and by segment, and uses that structure for the section 6 relativities.
- **Outputs.** M3 tables are saved in `outputs/m3_draft/` in the section 6 column shape. Combined pure-premium
  bounds are approximate and labelled so.
- `statsmodels` is approved as a main dependency. `scikit-learn` waits until M4.
Why: the rating engine needs a multiplicative structure, but forcing it on the risk model would hide which
structure predicts best. Separating the two keeps the choice honest and the approximation measurable.
Alternatives: assuming a frequency x severity model on event counts (rejected as a starting point, because claim
count is unknown at quote time), and requiring an exactly multiplicative risk model (rejected, it would limit
the candidates).

## 2026-11-02 Benefit types for the stacked candidate (issue #24)
Decision: `mart_person_year_benefit` has one row per person-year per benefit type, with both rows present for
every person-year in `mart_person_year` (zeros where there are no in-scope events). The benefit types are
`inpatient_daycase` and `outpatient`. `mart_person_year` is unchanged.
- **Inpatient and day-case** holds every in-scope inpatient stay, and every in-scope outpatient or office-based
  visit where `SURGPROC` (a surgical procedure was performed on the visit) is 1. **Outpatient** holds all other
  in-scope visits. `SURGPROC` exists in all four visit files and is passed through the staging views. The user
  approved using it on 2026-11-02. The classification is the `benefit_type` column of `int_events_pmi`.
- `SURGPROC` values -1 (inapplicable), -7 (refused) and -8 (don't know) are treated as no procedure, so those
  visits are `outpatient`. Of all visits in the files, -1 is 12.6% (2022) and 12.4% (2023) of hospital
  outpatient visits and 8.3% and 8.0% of office-based visits, and -7 or -8 is 0.4% to 0.7%. If a procedure
  was recorded as inapplicable, those visits are missed from `inpatient_daycase`. A rule for the five
  allowed values is in the staging `schema.yml`.
- Event counts and costs summed over the two benefit types equal `claim_count`, `claim_cost` and
  `claim_cost_2023_prices` in the mart. A dbt test checks this for every person-year.
- **What moves.** Of all in-scope events in the event files, `SURGPROC` moves 4,198 of 66,406 (6.3%) in 2022 and
  3,847 of 61,792 (6.2%) in 2023, which is 19.8% and 18.0% of their cost. By file in 2022, 5.1% of office-based
  events (14.4% of cost) and 11.5% of outpatient events (44.8% of cost). In 2023, 4.8% (12.4%) and 12.8% (48.7%).
  These figures cover every person in the event files, including zero-weight people. In the modelling table,
  `inpatient_daycase` has 7.4% of events and 47.5% (2022) and 53.8% (2023) of cost at 2023 prices.
Known limitations:
- `SURGPROC` is a yes or no for the whole visit. A minor procedure in a doctor's office, such as a skin biopsy,
  counts as day-case, which UK private medical insurance would usually treat as outpatient.
- Hospital outpatient visits with a procedure are close to UK day surgery, but there is no length-of-stay
  or admission flag to confirm it.
Why: the stacked candidate needs a benefit split that matches how a UK policy prices cover, and the survey's
procedure flag is the only direct indicator. A plain inpatient versus visit split would put day surgery in
outpatient.
Alternatives: inpatient stays only versus all visits (rejected by the user in favour of the procedure flag), and
treating office-based procedures as outpatient (a possible sensitivity, since they are 5% of office events).

## 2026-11-02 Rating-factor level grouping (decision gate 6, issue #26)
Decision: the user approved the grouping for the 18 rating-factor candidates, with two additions. The map is
saved as `outputs/m3_draft/level_grouping.csv` (one row per factor and level, with a flag for the reference group)
and is built by `levels.decided_grouping`. Evidence is in `notebooks/03_glm.ipynb`, using the 2022 train split.
- **Age.** Five-year bands: 0 to 4, 5 to 14, 15 to 17, 18 to 24, then five-year bands to 75 to 79, and 80 and over
  (16 bands, age capped at 85). The fewest claimants in any band is 108. The technical reference is 5 to 14, the
  band with the most exposure. For presentation only, age relativities are rebased to the adult band with the most
  exposure, which is 65 to 69 (1,300 exposure years). The rebasing does not change the fitted model.
- **`not_applicable` and null answers.** Merge into the reference level. No factor has more than 165 null
  person-years.
- **`unknown`.** Kept as a level in the fit only, and priced at the reference, where merging it into the reference
  would move the reference cost per exposure year by more than 2 percent. Merging changes the reference cost by
  +5.8 percent for `OFTSMK53` and +12.2 percent for `PHYEXE53`, so those two keep it. For the other 11 variables
  the change is under 1 percent (HIBPDX -0.8, CHOLDX -0.8, ARTHDX -0.7, the rest -0.6 or less, ASTHDX and DIABDX_M18
  about 0), so `unknown` merges into the reference. `levels.unknown_rule_table` shows the figures and a test checks
  that the kept levels are exactly those above 2 percent.
- **Thin levels.** Any other level with fewer than 30 train claimants merges into the reference. No real answer level
  is thin today, so this changes nothing now.
- **Reference level.** The real answer with the most exposure, never a placeholder.
- **Raised for gate 7.** `inscov` is kept at three levels for now. Its two options are in the notebook and are decided at
  gate 7: restrict the modelling population to privately insured persons, or keep everyone with `inscov` as a control
  priced at the private level.
Why: levels with few claimants give unstable relativities, and the `unknown` level is a leaver marker for the two
lifestyle questions, so merging it would distort every relativity for that factor. The 2 percent test makes the
treatment of `unknown` a measured rule and not a judgement for each variable.
Alternatives: ten-year age bands (same minimum claimant count, but they hide slope inside a band, for example a claimant rate of 49
percent at ages 55 to 59 and 56 percent at 60 to 64 in one band), and merging `unknown` for the lifestyle questions (rejected because
of the distortion above).

## 2026-11-02 Large-claim cap and provisional load (decision gate 5, issue #27)
Decision: the user approved a cap and a load for the M3 comparison, with additions. Evidence is in the "Large
claims" section of `notebooks/03_glm.ipynb`, on the 2022 train claimants (7,229) with the test split used as a
check only. The functions are in `health_pricing.models.large_claims`.
- **Cap.** A fixed 100,000 dollars on annual PMI-scope cost per person-year at 2023 prices. It caps 32 train
  claimants (0.44 percent) and removes 6.1 percent of train cost, and sits just above the 99.5th percentile
  (92,709). `mart_person_year` is unchanged. When costs are projected to the rating period in M6, the cap is
  indexed with the same trend.
- **Stacked candidate.** The person-year total is capped and the capped amount is shared between the benefit types
  in proportion to their uncapped cost (`capped_benefit_cost`), so every candidate predicts the same capped quantity.
- **Load.** A flat 6.5 percent of capped cost, from train (2.31 million dollars of excess over 35.77 million of
  capped cost, 6.47 percent). It is provisional and used for the M3 comparison only. It is not set from the test
  split or from 2023, and there are no segment loads.
- **Test shortfall.** The test split has a heavier tail (11 claimants above the cap, 10.8 percent of cost, an implied
  load of 12.1 percent). Any test A/E shortfall that comes from this sampling noise is expected. The diagnostics
  (issue #33) report its size and do not tune the model or the load to remove it.
- **Follow-up (M6).** Re-estimate the load on the pooled 2022 and 2023 rows for the final model, preferably by
  fitting a tail distribution above the cap such as a generalised Pareto, and compare it with the empirical load.
  Also index the cap with the projection trend.
Why: the tail rests on a few people, so a fixed cap keeps the largest person-years from dominating severity while
leaving most of the signal. Segment loads rest on 6 to 16 claimants and do not reproduce on test, so they would
price noise. Holding the load to train keeps the test split a clean holdout.
Alternatives: caps of 50,000 (109 claimants, 13.9 percent of cost removed), 250,000 (4 claimants), and the 99th,
99.5th and 99.9th percentiles (sample dependent). A higher load taken from the test split, and loads by age group or
benefit type.

## 2026-11-02 Candidate models (a), (b) and (c): fitting choices (issues #28, #29, #30)
Decision: the candidates are fitted by `health_pricing.models.glm` and `stacked` with `statsmodels`, which the user
approved as a main dependency. Scores are in `outputs/m3_draft/scores_candidate_a.csv`, `_b.csv` and `_c.csv`, and the
evidence is in `notebooks/03_glm.ipynb`. These are modelling choices within the approved plan and not decision gates.
- **Claimant indicator.** The frequency target is whether the capped annual cost is above zero, so the Gamma severity
  model sees only positive costs. This drops 34 of 7,229 train claimants (0.5 percent) and 6 test claimants whose
  recorded claims have a zero cost. The claim count is never a weight or a predictor.
- **Factors.** All 18 rating factor candidates are used by every candidate, so the structures are compared on the same
  inputs. `inscov` is an ordinary factor in this comparison. The factor set for the final structure, including
  `inscov`, is decided at gate 7.
- **`unknown` control.** The same people are `unknown` on the smoking and exercise questions, so the two `unknown`
  columns are identical. They are replaced by one `unknown_control` column that is fitted and then set to zero (priced at
  the reference) when predicting. This follows the gate 6 decision.
- **Scoring.** Predictions are capped expected cost plus the provisional 6.5 percent load, scored against the uncapped
  annual cost of the 2022 test split with the shared metrics. Poisson claimant counts can exceed 1 and are not capped.
- **Gamma dispersion** is estimated from the Pearson chi-squared, the `statsmodels` default. It is 5.25 for (a) and (b)
  and 5.35 for (c).
- **Candidate (c).** The `benefit_type` x age interaction is tested by the fall in deviance, divided by the Gamma
  dispersion for severity, against a chi-squared distribution. The frequency part is significant (80.5 on 15 degrees of
  freedom) and the severity part is not (10.7 on 15, p = 0.78). Two versions are scored, `c` with main effects only and
  `c_age_interaction` with the interaction in the frequency part. Standard errors are clustered by person. The tests
  treat rows as independent, so their p-values are approximate.
Results on the 2022 test split (baseline deviance 928,364): (a) 808,193, Gini 0.433, A/E 1.080. (b) 816,054, 0.428,
1.066. (c) 809,923, 0.432, 1.065. (c) with the age interaction 814,569, 0.431, 1.054. The ranking is for the model
comparison in the next task and is not a choice.
Why: a positive-cost indicator keeps frequency times severity equal to expected cost. One control column avoids an
exactly collinear design. The interaction is kept out of the severity part because it is not supported by the test.
Alternatives: keep zero-cost claimants and fit severity with a small floor (rejected as an arbitrary value), or merge
the two `unknown` levels into the reference (rejected at gate 6).

## 2026-11-02 Model structure and the surrogate model (tariff) check (decision gate 7, part 1, issue #32)
Decision: the user chose candidate (a), the binomial cloglog claimant frequency with a Gamma severity, as the risk
model, provisional until a surrogate model (tariff) check confirmed it. The check confirmed it. Evidence is in the
"Model comparison" section of `notebooks/03_glm.ipynb`, and the scores are in `outputs/m3_draft/model_comparison.csv`.
- **Surrogate model (tariff).** A multiplicative log-link GLM (Poisson family, log exposure offset) fitted to (a)'s
  predicted annual cost on the train split, and not to actual claims, with the same 18 rating factor candidates and
  the `unknown` control priced at the reference. It is also called tariff extraction, or fitting a rating structure to
  the technical premium. The code is `health_pricing.models.surrogate`.
- **Departure from (a).** The median absolute relative difference is 4.7 percent on train and 4.8 percent on test, the
  99th percentile is 30 percent, and the largest is 63 percent on train and 53 percent on test. Total predicted cost
  is kept (ratio 1.000 train, 0.998 test). It has 43 parameters against 88 for (a).
- **Test yardstick (p = 1.5, with 1.3 and 1.7).** Deviance of the surrogate model (tariff) 814,292 against 816,054 for
  (b) and 808,193 for (a), and the order (a), surrogate model (tariff), (b) is the same at all three powers. The
  Gini is 0.426 against 0.428 for (b) and 0.433 for (a). Against (b) the deviance difference is -1,762 with a household
  bootstrap interval of -5,752 to 1,756 (better in 83 percent of resamples), so the margin is small and within noise.
  The surrogate model (tariff) is nearer 1 than (b) in 7 of 10 double-lift groups.
- **Rule applied.** If the surrogate model (tariff) of (a) beats (b), confirm (a), and otherwise choose (b). It beats (b)
  on the Tweedie deviance at all three powers, so (a) is confirmed. The Gini is marginally lower than (b)'s and the
  deviance gap is within noise, so the check shows (a) keeps its position when put into a multiplicative form and does
  not show a clear win.
- **(a) over (c).** The two are statistically indistinguishable, so (a) is chosen on simplicity. (c), the stacked
  candidate, is the option if the product layer later needs separate inpatient and outpatient pricing, for example an
  outpatient limit.
- **Candidate (d) and cross-validation.** The optional event-based candidate (#31) is skipped. No pooled
  cross-validation is done now. Grouped cross-validation happens in M4 with the LightGBM tuning.
- **`inscov`.** Everyone is kept, and `inscov` is fitted as a control and priced at the private level.
- **Factors.** The factor set is decided in a new task, "Permitted factors and factor selection (gate 7, part 2)",
  placed between #32 and #33. Self-rated health (`rthlth`, `mnhlth`), exercise (`PHYEXE53`) and `inscov` are
  analysis-only. An option with the condition flags analysis-only as well is also presented, because UK individual PMI
  usually handles pre-existing conditions through exclusions (moratorium or full medical underwriting) and not premium
  loadings. Diagnostics (#33) and relativities (#34) use the final factor set.
- **Test A/E.** The overall test A/E of 1.08 and the level-by-level failures are consistent with a small test split,
  a heavy tail and the provisional large-claim load. They are noted in the notebook and are not tuned away.
- **M4.** The plan for M4 now includes a surrogate model (tariff) of the tuned gradient-boosting model, compared with
  the GLM's surrogate model (tariff) on the holdout.
Why: a rating engine holds a multiplicative tariff, so a structure that is not exactly multiplicative has to be
compared after it is put into that form. The check keeps the yardstick the same and tests whether (a)'s advantage
over the already multiplicative (b) survives.
Alternatives: choose (b), which is exactly multiplicative, and choose (c) for the benefit-type split.

## 2026-11-02 Permitted factor options: fitting choices (issue #39)
Decision: these are the choices made to compare the permitted-factor options. The choice of the final factor set is
decision gate 7, part 2, and is the user's. Evidence is in the "Permitted rating factors" section of
`notebooks/03_glm.ipynb` and in `outputs/m3_draft/permitted_factor_options.csv` and `factor_tests.csv`. The code is
`health_pricing.models.factors`.
- **Analysis-only factors** are fitted as controls and priced at their reference level, as agreed for `inscov`.
- **Rebalancing.** Pricing a control at its reference level leaves the base rate too low for the book, because the
  reference level is not the average. Each option's predictions are scaled so that predicted cost on the train split
  equals actual cost on train. The factors are 1.012 (all factors), 1.156 (option 1) and 1.941 (option 2). Without
  rebalancing the test A/E would be 1.25 and 2.10 and the deviance would hide the ranking power. The test split is not
  used to set it.
- **Tests and AIC.** Each rating factor is dropped in turn from candidate (a). The likelihood-ratio statistic is the fall
  in deviance over both parts, with the severity part divided by the full model's Gamma dispersion, and the change in AIC is
  the statistic minus twice the extra degrees of freedom. The `statsmodels` AIC for a Gamma model is not used, because it
  evaluates the likelihood at each model's own estimated dispersion and so is not comparable across models. A selection
  rule of keeping a factor when AIC improves gives 11 of the 14 option 1 factors.
- **Results (test split, p = 1.5).** All factors 807,324 (Gini 0.433). Option 1 829,537 (0.393). Option 1 selected by AIC
  829,405 (0.394). Option 2 854,746 (0.329). Intervals for the differences from all factors include zero.
- **Not supported by the tests in option 1:** heart attack (`MIDX`), stroke (`STRKDX`) and diabetes (`DIABDX_M18`).
  Angina (`ANGIDX`) is borderline.
- **Exercise** is analysis-only. Adults who do not exercise cost 31 percent more before adjustment, and the adjusted
  relativities are 0.97 for frequency and 1.07 for severity, both consistent with 1.
Alternatives: leave an analysis-only factor out of the fit instead of fitting it as a control (not done, because a
control keeps the other relativities unconfounded), and keep the `statsmodels` AIC.

## 2026-11-02 Permitted factors and the final factor set (decision gate 7, part 2, issue #39)
Decision: the user decided the permitted factors and the factor rule, from the evidence in the "Permitted rating
factors" section of `notebooks/03_glm.ipynb`. The final structure is candidate (a) with 10 rating factors. The fitting
choices behind the evidence are in the entry "Permitted factor options: fitting choices (issue #39)" above.
- **Structure.** Candidate (a) is confirmed. (a) keeps its position in multiplicative form, not a clear win.
- **Permitted set.** Option 1. Self-rated health (`rthlth`, `mnhlth`), exercise (`PHYEXE53`) and `inscov` are
  analysis-only. They are fitted as controls and priced at their reference level.
- **Rebalancing.** The base rate is rescaled so that predicted cost on train equals actual cost on train, and the test
  split is not used. It applies to every option and to the final tariff.
- **Factor rule.** Keep a rating factor only if the likelihood-ratio test gives p < 0.05 and AIC improves. It drops
  `MIDX` (p = 0.68), `STRKDX` (0.63), `DIABDX_M18` (0.32) and `ANGIDX` (0.096), which leaves 10 rating factors: age,
  region, smoking (`OFTSMK53`) and the flags for high blood pressure, coronary heart disease, other heart disease,
  cholesterol, cancer, arthritis and asthma. `ANGIDX` fails the p-value part of the rule. Its AIC improves marginally
  (by 0.7) when it is kept, so it is dropped on the p-value alone and not because AIC is worse.
- **Result (test split, p = 1.5).** The final 10 factors score 826,675 (Gini 0.399) with 80 parameters. All 18 factors
  score 807,324 (0.433), option 1 scores 829,537 (0.393) and option 2 scores 854,746 (0.329). The final set is slightly
  better than option 1, so the dropped factors added nothing on the test. Intervals for the differences from all factors
  include zero.
- **Diabetes sensitivity.** Given the final 10 factors, `DIABDX_M18` has relativities of 0.96 (frequency) and 0.91
  (severity), and adding it back raises the test deviance by 1,909.
- **Limitation.** The condition flags stand in for underwriting. UK private medical insurance would exclude claims
  linked to pre-existing conditions, and modelling that needs a link from each condition to each claim, which is out of
  scope. Option 2 is kept as a sensitivity. It removes the loadings but still pays those claims, so it overstates the
  loss.
- **Exercise** is kept as an insight section and not a rating factor. The raw gap is 31 percent, but the adjusted
  relativities (0.97 frequency, 1.07 severity) are consistent with no effect, so the raw gap reflects who exercises and
  not a causal effect. A randomised design would be needed to estimate the effect.
- **Folded into later tasks.** Diagnostics (#33) and relativities (#34) use the final 10 factors. #33 also shows lift
  charts on train and test with household-resampled bands and a five-group version, and compares the lowest and highest
  group A/E of the final set with the all-factor model. If over-spreading persists, a penalised GLM (ridge or elastic net)
  is an option for the next gate and is not built before then.
Why: a factor that the tests do not support adds parameters without ranking power, and the final set keeps most of the
ranking of the full model. Condition flags are kept as a stand-in so that the plan's simulation of full medical
underwriting can proceed.
Alternatives: option 2 (rejected as the base, kept as a sensitivity), keeping all 14 option 1 factors, and a
less strict rule that keeps a factor on AIC alone.

## 2026-11-02 Diagnostics and relativities of the final structure (issues #33 and #34)
Decision: these are findings and presentation choices for the final structure (candidate (a) on 10 rating factors,
rebalanced on train). No model choice changes. Evidence is in the "Diagnostics of the final structure" and "Relativities of
the final structure" sections of `notebooks/03_glm.ipynb`, and in `outputs/m3_draft/` (`ae_by_level.csv`,
`residuals_by_decile.csv`, `lift_by_group.csv` and the four `relativities_*.csv` tables).
- **Overall A/E.** Train 1.000 (within 2 percent by construction of the rebalancing). Test 1.080, outside 5 percent, with
  a household band of 0.90 to 1.29. The test excess over the cap is 12.1 percent of capped cost against the 6.5 percent in
  the provisional load, and with a matched load the test A/E would be 1.03. The gap is consistent with a small test split,
  a heavy tail and the provisional load, and is not tuned away.
- **A/E by level.** Rating factors have 7 of 38 levels outside 0.85 to 1.15 on train and 19 of 37 on test. On train the
  four age bands up to 24 are over-predicted by about 20 to 35 percent, which is consistent with self-rated health being
  analysis-only and a single rebalancing factor. On test the pattern is mostly noise. 18 of the 19 household bands contain 1, and the condition flags lean towards
  over-spreading only weakly.
- **Lift and over-spreading.** On test the all-factor model over-predicts the top group by 27.5 percent and the final
  set does not (A/E 1.02), so the final set does not show it, although the household bands overlap and the difference is not established. The lowest group is over-predicted on
  train in both (0.49 final, 0.63 all factors), which points to the form of the model, and is too noisy to read on test.
  Over-spreading is weak or mixed in the final set on this evidence, so no penalised GLM is proposed. It remains an option
  at a later gate if the user asks.
- **Relativities.** Frequency and severity relativities are saved with 95 percent bounds, and the combined pure premium
  relativity is their product with bounds that treat the two as independent (approximate). Age is also shown against the
  adult band with the most exposure (65 to 69), and the technical reference stays 5 to 14. A prediction recomputed from the
  base values and relativities matches the model to 1e-8.
- **Tariff.** The surrogate model (tariff) of the final structure has a median departure of 3.2 percent, a 99th percentile of
  19 percent and a largest of 62 percent. On test its deviance is 0.95 percent higher than the final structure's and its Gini
  is 0.390 against 0.399. Its relativities are smaller than the product of the parts for high-risk levels (cancer 1.79
  against 2.29), because the chance of a claim cannot exceed 1. Which table is the published one is settled in the
  multiplicative rating structure task.
- **Flag for review.** The smoking relativities are below 1 (0.60 daily, 0.69 occasional against non-smokers), the opposite of
  UK pricing assumptions. The factor passes the selection rule and stays in. The sign is flagged and the result is not a
  finding that smoking lowers cost.

## 2026-11-02 Smoking check and age curve: findings for the gate (issues #40 and #41)
Decision: none yet. These are findings and recommendations, and the choices are the user's. Evidence is in the "Smoking
check" and "Age curve" sections of `notebooks/03_glm.ipynb` and in `outputs/m3_draft/` (`smoking_*.csv`,
`age_curve_*.csv`). The code is `health_pricing.models.smoking` and `agecurve`.
- **Smoking.** Removing the condition flags barely moves the smoker relativity (daily 0.600 with and 0.596 without,
  occasional 0.688 and 0.733), so the flags do not absorb the discount. Dropping the self-rated health controls as well raises it to 0.736 (0.57 to 0.95) for daily smokers, so health explains part of it. The rest is mostly in frequency (about 0.70 to 0.75 daily). The direction is the same in the three adult age groups before and after adjustment, with the evidence strongest at 40 and over (crude cost for all smokers 0.86, 0.71 and 0.82 at 18 to
  39, 40 to 64 and 65 and over, adjusted daily smokers 0.52, 0.49 and 0.67). The pattern fits a difference in the use of
  care, and the data cannot separate lower need from lower use. Recommended: make smoking analysis-only, which leaves 9
  rating factors, and put no smoker discount in the tariff. The alternative is a floor at 1.00.
- **Age curve.** An adult natural spline with 4 degrees of freedom has 64 parameters against 80 for the five-year bands, and
  its AIC (at a common Gamma dispersion) is 20.1 lower. Against a model that holds both, the bands add nothing beyond the
  spline (p = 0.134) and the spline adds something beyond the bands (p = 0.011). On the test split the bands are 0.2 percent
  better on deviance (826,675 against 828,268) and 0.006 higher on Gini, within noise. The 3-degree spline is not
  distinguishable from the bands. Recommended: read the tariff's band relativities off the smooth curve, which removes
  irregularities at ages 35 to 39, 40 to 44 and 70 to 74.
- **Rebased age intervals.** The age relativities against the 65 to 69 band now have intervals from the covariance matrix
  (70 to 74 is 1.21, 0.94 to 1.55), saved as `presentation_lower_95` and `presentation_upper_95`. The earlier note that the
  intervals were on the technical base is replaced by this.
- **Code.** `design_matrix` and `fit_two_part` accept numeric columns, which carry the spline terms.
Alternatives: floor smoking at 1.00 instead of analysis-only, and keep the five-year bands as fitted.

## 2026-11-02 Smoking and age decisions (issues #40 and #41)
Decision: the user decided the smoking and age questions raised in the findings entry above, after QA passed both
checks. The final structure is candidate (a) with 9 rating factors. Evidence is in the "Smoking check" and "Age curve"
sections of `notebooks/03_glm.ipynb`.
- **Smoking is analysis-only.** It passes the factor rule but is made analysis-only, which leaves 9 rating factors (age,
  region and the flags for high blood pressure, coronary heart disease, other heart disease, cholesterol, cancer, arthritis
  and asthma). It is still fitted as a control, so it adjusts the other relativities, and it is priced at the non-smoker
  level. There is no smoker discount in the tariff.
- **Evidence for smoking.** Removing the condition flags leaves the smoker relativity unchanged (daily 0.600 with and 0.596
  without). Dropping self-rated health as well raises it to 0.736 (0.57 to 0.95), so health explains part of it. The rest is
  mainly in frequency and is already present in the crude data (crude cost for all smokers 0.86, 0.71 and 0.82 at ages 18 to
  39, 40 to 64 and 65 and over). It is consistent with US access to care, and the data cannot separate lower need from lower
  use.
- **Smoker loading.** If a smoker loading is wanted in a later product layer, it must be an explicit judgement loading from an
  external source, labelled as not derived from this data. It is not built.
- **Age.** The tariff's band relativities are read off the adult natural spline with 4 degrees of freedom, and the five-year
  bands stay as the format of the rating table. After smoothing, the base rate is rebalanced on train so that train predicted
  cost equals train actual cost. The intervals for age against the 65 to 69 band come from the covariance matrix
  (`presentation_lower_95` and `presentation_upper_95`).
- **Numbers.** The final structure scores a test deviance of 830,232 (Gini 0.393, 80 parameters, rebalancing factor 1.115). The
  final tariff scores 838,173 (Gini 0.378, 26 parameters), departs from the banded structure by a median of 5.5 percent, and has
  a test A/E of 1.081 (band 0.90 to 1.28).
- **Tables.** `relativities_tariff.csv` is the final tariff. `relativities_tariff_banded.csv` is the banded tariff for
  comparison, and the frequency, severity and combined tables hold the component relativities with their intervals.
Why: a smoker discount has no support as a risk effect and would carry a factor with no effect if floored, and the smooth
curve removes irregularities between bands that look like noise while keeping the table format.
Alternatives: floor the smoker relativity at 1.00, and keep the age relativities as fitted by band.

## 2026-11-02 Model specifications and descriptive model names in the GLM notebooks
Decision: after the notebook review, `notebooks/03_glm.ipynb` has a "Model specifications" section after "Data and metrics",
with the notation, the equations of each candidate, the final structure, the smooth age model and the surrogate model
(tariff), a comparison table, and the definitions of the Tweedie deviance and the exposure-weighted Gini. Models carry
descriptive names with their letters in every table, chart legend and saved file, namely "(a) Binomial-cloglog × Gamma",
"(b) Poisson × Gamma", "(c) Stacked by benefit type", "(c) Stacked with age × benefit interaction" and "(a) Surrogate
model (tariff)". Deviance is shown with its percentage reduction against the baseline of the same split in the comparison,
option and final score tables and in the headline tables. `03_glm_summary.ipynb` shows the comparison table, the equations
of the chosen model and the final tariff, and a lift chart of the final tariff with household bands.
- The final structure that is scored (80 parameters, test Gini 0.393) has age in five-year bands. The final tariff is fitted
  to the same structure with a smooth adult age curve (64 parameters, test Gini 0.386), so the tariff's lower Gini (0.378)
  comes about half from smoothing age (0.393 to 0.386) and half from the multiplicative approximation (0.386 to 0.378), with the approximation the larger part of the deviance rise.
- The internal option names `all_factors`, `option_1`, `final` and `final_tariff` are not renamed.
Why: a reviewer needs to check what is fitted, and the letters alone did not say.
Alternatives: keep the short keys in tables, or rename the option names too.

## 2026-11-02 Frequency trend and the 2023 gap: evidence for the gate (decision gate 4, part 2, issue #43)
Decision: none yet. This is the evidence and a recommendation, and the choice is the user's. Evidence is in the "Frequency
trend and the forecast assumption" section of `notebooks/04_monitoring.ipynb` and in `outputs/m5_draft/`. The code is
`health_pricing.models.trend` and `health_pricing.data.urr`.
- **Rule.** The forecast trend for the out-of-time test is set without looking at 2023. The trend that the 2022 to 2023 data
  imply is a diagnostic only, and is never used as a forecast, because that would make the 2023 A/E close to 1 by construction.
  A trend is a factor on the claim hazard (`1 - (1 - p)^f`), so the claim probability stays below 1.
- **External source.** CMS Unified Rate Review public use file, plan year 2023, Worksheet I, file
  `PY2023_WKSH1_PUF_20221027.csv` in `2023-urr-puf.zip` (CMS update of 1 November 2022, size 9,755,168 bytes, SHA-256
  `e1eb4a1533c406a79245851b1e619fc56b087dd94f941f7379a767ba6f53caad`). Filings made in 2022. 713 filings with a
  calendar-year 2021 experience period and a projection from 1 January 2023, 275.5 million member months. The Year 2 trend runs
  from 2022 to 2023. Member-month weighted median utilization trend 1.5 percent (inpatient), 2.5 percent (outpatient) and
  1.9 percent blended by experience claims share (quartiles 0.8 and 3.1 percent). The measure is utilization per member
  for US commercial filings, which is not the same as the share of person-years with a claim.
- **Context, not an input.** CMS National Health Expenditure actuals for 2023 (Health Affairs, 18 December 2024) show real growth
  of 4.4 percent in 2023 against 1.4 percent in 2022, mainly from use and intensity. The June 2023 CMS projection had private
  health insurance spending rising 7.7 percent in 2023.
- **The gap.** Cost per exposure year rose 16.9 percent (5.9 to 29.3). Mix 0.1 percent, frequency 2.7 percent (0.2 to 5.3),
  severity beyond the price index 13.9 percent (5.6 to 23.0), large claims -0.3 percent. Frequency and severity are
  changes in the cost of the same people and are level-change candidates if they persist. Mix and large claims are not.
- **A/E on 2023.** Technical model 1.167 with no trend, 1.155 with the external median, 1.139 with the trend the data imply
  (diagnostic only). The tariff gives the same figures. The choice of forecast moves A/E by about one point.
- **Large-claim load.** The 2023 cost over the cap is 6.2 percent of capped cost against the provisional 6.5 percent, so no part
  of the gap is consistent with the load. Nothing is tuned for it.
Recommendation: the external median of 1.9 percent as the central forecast, with 0.8 and 3.1 percent as the range. None (0
percent) gives the same conclusion within one point of A/E.

## 2026-11-02 Forecast trend for the out-of-time test (decision gate 4, part 2, issue #43)
Decision: the user decided the forecast trend after seeing the evidence logged above.
- **Central forecast.** The CMS Unified Rate Review median utilization trend, 1.9 percent, with 0.8 and 3.1 percent (the quartiles) as
  the sensitivity range. Source: CMS Unified Rate Review public use file for plan year 2023, Worksheet I, file
  `PY2023_WKSH1_PUF_20221027.csv` in `2023-urr-puf.zip`. Vintage: filings made in 2022, file updated by CMS on 1 November 2022.
  Value: member-month weighted median Year 2 utilization trend over 713 filings (calendar-year 2021 experience, projection from
  1 January 2023), 1.5 percent inpatient, 2.5 percent outpatient, 1.9 percent blended by experience claims share.
- **How it is applied.** As a utilization trend on expected annual cost (expected cost × 1.019), for both the technical model and the
  tariff. The URR utilization trend is services per member, and in this structure most extra use appears as more claims per claimant
  (claims per exposure year +9.3 percent against a claimant rate +2.7 percent), so a trend on the claim hazard alone would leave out
  most of it. The hazard-only application is shown alongside for comparison, and 0 percent is a further sensitivity.
- **Not used.** The trend that the data imply is a diagnostic only. It is never used as a forecast, because that would make the 2023 A/E
  close to 1 by construction.
- **Reading.** The severity component (+13.9 percent, interval 5.6 to 23.0) is mainly intensity, meaning more services per claimant,
  consistent with the CMS National Health Expenditure finding that growth in 2023 was driven by use and intensity with low price
  growth. The MEPS magnitude is well above the national real growth of 4.4 percent, so it is noisy and is not to be taken at face
  value.
- **Result.** Technical model A/E on 2023 of 1.145 (1.075 to 1.220) under the central forecast, 1.158 at 0.8 percent, 1.132 at 3.1
  percent and 1.167 with no trend. The hazard-only application of 1.9 percent gives 1.155. The tariff gives the same figures.
- **For the recalibration rule (#47).** The 2023 evidence points to a level change, but the rule should weight one year of noisy
  experience by its credibility and not recalibrate fully.
Why: an external, pre-2023 actuarial view keeps the out-of-time test a test of a forecast.
Alternatives: no trend as the central forecast, the National Health Expenditure projections, and a trend on the claim hazard only.

## 2026-11-02 Forecast trend: wording after QA (issue #43)
Clarifications to the entry above. The split of the severity part between more claims per claimant (about 6 percent) and a higher
cost per claim (about 7 percent) is an inference from claims per exposure year and the claimant rate, whose intervals overlap, so
"mainly intensity" is a reading and not a measurement. The household intervals of the ratios resample 2022 and 2023 independently
although many people and households are in both years, so they are somewhat wider than they need to be. The data-implied trend would
make the frequency part of the 2023 A/E close to 1 by construction, and a cost A/E of 1.139 would remain.

## 2026-11-02 PSI drift choices (issue #46)
Decision: PSI is computed on exposure shares of the M3 levels, with age in its five-year bands. A share below 0.0001 is raised to
0.0001, so an empty level does not give an infinite PSI. Predicted cost is binned at the exposure-weighted deciles of 2022 train, for a
full year of exposure and with no trend, because a trend is a level factor that would move every row into higher bins together.
Each PSI is shown with a household-resampled interval and with the PSI that sampling noise alone gives, approximated by
`(levels - 1) * (1 / n1 + 1 / n2)` on person-year counts. The resampled interval is not a confidence interval. Both periods are resampled,
so it sits above the PSI of the data when the true PSI is near zero. The chart uses a symmetric log axis because every PSI is below 0.01.
Why: the reading bands of 0.1 and 0.25 are conventions, and the question is whether the movement is more than noise.
Alternatives: a permutation test for the noise level, which is more exact and could replace the approximation in M9.

## 2026-11-02 Recalibration rule and its thresholds (issue #47)
Decision: the rule in `_docs/recalibration-rule.md` and `src/health_pricing/models/recalibration.py`. Structure has moved if either Wald
p-value for the relativities is below 0.05, or the count of rating levels beyond noise (stability) or off the book (A/E) is more than
chance gives (binomial p below 0.05 at 5 percent per level). The mix has moved if the largest PSI is above 0.1. The ranking is lost
if the Gini is more than 0.05 below the 2022 test split. The actions are: do nothing, rebase, refit the relativities, or review the
structure. A rebase is credibility-weighted and reported as a range. The sampling weight is the square root of the claimants over the
limited-fluctuation standard (90 percent probability of being within 5 percent, 1,082 times one plus the squared coefficient of
variation of severity). The persistence weight is `spread^2 / (spread^2 + standard error^2)` with a spread of 1.7 percent, from the
quartiles of the CMS utilization trend.
Result on 2023: rebase, with a base-rate factor between 1.025 (persistence weight 0.17) and 1.145 (sampling weight 1.00) on the
forecast cost. The structure did not move, the mix did not move and the ranking held. The choice within the range is left to the user.
The large-claim load is handled apart. Matching it to the 2023 excess would add 0.37 points to the A/E.
Why: one noisy year should not be priced in full, and the data cannot say how much the level drifts, so the range is shown and not hidden.
Alternatives: a single credibility from a Buhlmann model with an estimated drift, which needs more years, and a full rebase.

## 2026-11-02 Trend sensitivity: the total move (issue #48)
Decision: the low, central and high trends are the lower quartile, median and upper quartile of the CMS utilization trend of gate 4,
part 2 (0.8, 1.9 and 3.1 percent). The conclusions are compared through the recalibration rule under each trend, and through the
total move, which is the trend times the rebase factor, meaning the level of 2023 cost against the 2022 train level. At the sampling
weight the total is the same under every trend (1.167), because a higher trend leaves less to rebase. At the persistence weight it is
1.035, 1.045 and 1.055, so the trend matters a little there. The rule gives a rebase under all three, and the trend has no effect on
the relativities.
Why: the trend is a level factor, so the useful question is how much of the level it explains and whether the action changes.
Alternatives: showing only the A/E under each trend, which hides that the trend and the rebase offset each other.

## 2026-11-02 ER-originated stays sensitivity: method (issue #49)
Decision: the broadened cost of a person-year is its base cost plus its ER-originated stay cost, both at 2023 prices, and a person
with such a stay is a claimant. The large-claim cap stays at 100,000 dollars and the provisional load is not re-estimated. The frozen
base model is scored on the broadened 2023 cost, and the same structure is refitted on the broadened 2022 train cost and scored on
the broadened 2023 cost, so that both the shift in level and the like-for-like A/E are shown. The relativity intervals treat the base
and broadened fits as independent although the broadened cost contains the base cost, so they are wide.
Result: the stays add 33.0 percent to 2023 cost and 2.8 percent to claimants. The base model A/E rises from 1.145 to 1.523, and the
refit has an A/E of 1.147. No relativity is beyond noise, the factor ranking is unchanged and the age curve ratio contains 1 at every age.
The base definition stays the approved one. Any change to the PMI-scope definition needs the user at decision gate 2.
Why: this is the sensitivity planned in the PMI-scope decision.
Alternatives: a larger cap for the broadened cost, which would need the pooled load estimate of M6.

## 2026-11-03 Rebase decision for the 2023 recalibration (issue #47)
Decision: the user decided a rebase of 1.06 on the forecast cost, a credibility-weighted level change. Own 2023 experience implies
+14.5 percent, but its severity component is noisy (interval 5.6 to 23.0 percent). The CMS National Health Expenditure real growth of
4.4 percent in 2023, against the 1.9 percent utilization trend already applied, implies about +2.5 percent. With a weight of 0.3 on
one year of own experience, the factor is `1 + 0.3 * 0.145 + 0.7 * 0.025`, which is 1.061 and is rounded to 1.06. The bounds shown are
1.025 (no weight on own experience beyond the external level) and 1.145 (full weight on the 2023 A/E).
Note: the M6 pooled refit with a year term estimates the level directly and supersedes this rebase.
Why: one noisy year should not be priced in full, and an external view of the level gives a prior.
Alternatives: the limited-fluctuation weight of 1.00 and the persistence weight of 0.17, reported in the entry of 2026-11-02.

## 2026-11-03 M4-lite: GBM challenger, tuning and result (issues #52 to #56)
Decision: one LightGBM model with a Tweedie objective (power 1.5) on capped annual cost per person-year, with log exposure as the init
score. Inputs are the 9 rating factors (adult age as a number, monotone increasing, children in age bands) and `inscov`, priced at
private when scoring. The prediction carries the provisional load of 6.5 percent and is rebalanced on 2022 train. Tuning is five-fold
cross-validation on 2022 train, grouped by household, over the 12 combinations of learning rate (0.03, 0.06), leaves (4, 8, 16) and
minimum rows per leaf (50, 150), with early stopping (patience 50) on the trees. Chosen: learning rate 0.06, 8 leaves, minimum 150
rows per leaf, 123 trees (mean best iteration of the folds), by the lowest out-of-fold deviance. The grid is flat: the deviances of
the 12 combinations lie within 0.3 percent. The grid and scores are in `outputs/m4_draft/gbm_cv_grid.csv`.
Result: on the 2022 test split the GBM has a deviance of 840,754 and a Gini of 0.378 against 831,786 and 0.386 for the GLM technical
model and 838,173 and 0.378 for the GLM tariff, all within noise. Its surrogate tariff has 843,827 and 0.368. On 2023 the A/E is 1.142
(GBM) and 1.145 (the others) and the Gini is 0.469, 0.460 (GBM tariff), 0.473 and 0.468. The GBM has no advantage over the GLM, so
there is nothing for its surrogate to keep. On 2023 deviance the GBM (3,518,700) is 0.6 percent below the GLM tariff (3,539,069) and 0.3 percent above
the technical model (3,506,653), and its tariff is 3,554,354. The double lift on 2022 test has the GLM tariff nearer 1 in 8 of 10 groups.
Why: a bounded challenger test before the pricing basis is chosen. The GLM is not changed.
Alternatives: more inputs (the health and exercise controls), a wider grid and more seeds, left for M6 if the user wants them.

## 2026-11-03 Pricing basis: the GLM tariff (M4-lite gate)
Decision: the user chose the GLM tariff as the basis for pricing, not the surrogate tariff of the GBM.
Evidence: the GBM does not beat the GLM on the 2022 holdout (deviance 840,754 against 838,173 for the GLM tariff, with a gap interval of
-18,656 to 11,028 that includes 0, and the same Gini of 0.378), the GLM tariff is nearer 1 in 8 of 10 double-lift groups, and SHAP finds
no interaction among the rating factors that the GLM misses. The GBM tariff is worse again (843,827 and a Gini of 0.368).
Diagnostic: refitted once without the age constraint, with the tuned values and no re-tuning, the GBM has a test deviance of 843,561
and a Gini of 0.372, so the constraint costs nothing on the data. At ages 80 to 85 its mean predicted cost against age 67 is 0.91 to
1.00, against 1.06 to 1.09 constrained and 0.87 to 0.78 for the GLM curve. It is not a pricing candidate. The monotone constraint stays
for pricing, because UK private medical premiums rise with age.
Optional, not run: a GBM given the health and exercise controls.
GLM tariff age check: the 80+ relativity (0.887 against the 65-69 band) is below 75-79 (0.949). The tariff also falls from 65-69 (1.000) to
70-74 (0.988) and 75-79. An M6 task floors the 80+ relativity at the 75-79 level for consistency with the monotone pricing rule, then
rebalances the base and reports the effect. The tariff is not changed now.
Why: the simpler model with intervals is as accurate, and a monotone age rule suits UK PMI.
Alternatives: the GBM surrogate tariff, which is more complex and less accurate here.

## 2026-11-03 Monotone adult age rule for the tariff (issue #57, M6)
Decision: the user chose one rule and not individual floors. The adult age relativities of the tariff (18 and over) must be non-decreasing.
The rule is an exposure-weighted isotonic adjustment (pool adjacent violators) of the adult band relativities, which smooths the dip
from 65-69 to 70-74 and the dip at 80+. Children's bands (0 to 17) are left as fitted. The base is then rebalanced on 2022 train, so
the train total equals that of the unadjusted tariff (a base-rate multiplier of 0.998). The rule is in `models/agemonotone.py`, the
frozen tariff of M3 is unchanged and the adjusted one sits beside it. It stays in M6.
Effect on the bands (relativities against the 65-69 band before the rule): the bands 60-64 to 80+ are pooled to 0.963. 60-64 moves
-0.3 percent, 65-69 -3.7 percent, 70-74 -2.6 percent, 75-79 +1.4 percent and 80+ +8.5 percent. All other bands are unchanged.
Effect on scores (2022 test): deviance 838,173 to 839,170 (+0.12 percent), Gini 0.3783 to 0.3763, A/E 1.0811 to 1.0810. On train the
deviance goes from 3,051,675 to 3,051,872.
A/E by band on test, before and after: 65-69 1.307 to 1.361, 70-74 0.814 to 0.837, 75-79 1.260 to 1.245, 80+ 0.821 to 0.759. The
other bands move by less than 0.01. Tables are in `outputs/m6_draft/`.
Why: UK PMI premiums rise with age, so the tariff should not charge a person of 80 less than a person of 70.
Alternatives: floors on the 80+ band only, and a monotone rule from 65-69 only.

## 2026-11-05 Monotone age rule as a tested function, with cross-validation (issue #57, v1-lite)
Decision: the rule is now the function `agemonotone.monotone_adult_rule`. It takes the band relativities, exposures and predicted cost by band,
and returns the monotone relativities and the base-rate multiplier that restores total cost. `adjust_tariff` applies it to any surrogate tariff.
Scope change: the issue asked for the pooled model. Under the v1-lite delivery scope (`_docs/plan.md`), the rule is checked on the 2022-fitted
tariff. The pooled bands are v2 work, and the limitation about UK market calibration of older ages stays.
Evidence: on a five-fold cross-validation grouped by household, with the tariff refitted in each fold, the out-of-fold deviance goes from
3,087,302 to 3,085,067 (-0.07 percent) and the Gini from 0.4749 to 0.4756. A/E is 1.0012 and 1.0010. The base-rate multiplier is 0.9965 to
0.9997 across folds, and 3 to 5 adult bands are pooled in each fold. Out-of-fold A/E by band, before and after: 65-69 1.021 to 1.061, 70-74 1.077
to 1.104, 75-79 1.113 to 1.096, 80+ 1.064 to 0.980. The holdout result (+0.12 percent deviance) is the opposite sign, so the effect on fit is
within noise either way. Tables are in `outputs/m6_draft/age_monotone_cv_*.csv`. The grouping of levels is kept as decided on the full 2022 train split.
Why: the rule is a pricing requirement and costs nothing measurable in fit.
Alternatives: floors on single bands, as logged on 2026-11-03.

## 2026-11-05 Final v1-lite tariff, evidence for gate 7 (issue #37)
Status: evidence and recommendation, awaiting the user's decision at gate 7.
Construction: the M3 tariff (surrogate of the technical model, five-year age bands, exposure offset), then the monotone adult age rule, then the base
rate rebalanced so total predicted cost on 2022 train is unchanged (multiplier 0.998). Scope change: the issue says pooled with a year term and the load
and trend applied. Under v1-lite the model is fitted on 2022 only, and the rating-period level is a factor on the base rate, the forecast trend of
1.019 times the decided rebase of 1.06 (1.080 together). Age is presented against the 65-69 band as fitted before the rule, so the base rate carries that band's pre-rule relativity. After the rule the 65-69 relativity in the table is 0.963, and the base rate is the cost of the reference profile at age 65-69 only before the rule.
Base rate: 1,828 at 2022 level and 1,975 at the rating-period level (dollars per exposure-year for the reference profile).
Bounds: each level keeps the width of the technical model's combined bounds (frequency and severity treated as independent), centred on the tariff
relativity. The 65-69 band has none, because the model measures age against it. The bounds show model uncertainty and are not a fit of the tariff.
Approximation error (tariff over technical model, by segment, test split, median and maximum absolute departure from 1): age band 0.5 and 8.2 percent
(80+, from the rule), factor level 0.3 and 1.1 percent, number of conditions 2.4 and 3.6 percent, predicted-cost decile 2.8 and 4.2 percent. Before the
rule the age band maximum was 1.1 percent. Train is similar. Tables are in `outputs/m6_draft/final_tariff_*.csv`.
Recommendation: adopt this tariff as the v1 tariff. The 8 percent gap at 80+ is the price of a non-decreasing age curve and is stated in the limitations.
Alternatives: no rule (the age relativity falls after 70), or a floor at 80+ only.
