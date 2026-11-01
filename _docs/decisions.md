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
  answer in any round and stay null.
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
