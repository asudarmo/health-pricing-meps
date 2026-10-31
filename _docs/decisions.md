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
