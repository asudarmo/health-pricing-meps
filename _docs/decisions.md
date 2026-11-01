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
