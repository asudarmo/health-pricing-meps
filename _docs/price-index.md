# Price index for on-levelling and trend projection

Decision gate 4 (`AGENTS.md`), the price index part (the frequency trend part was already
decided, see `_docs/decisions.md`, "2026-10-31 Trend"). This is the supporting evidence for issue
#6. Confirmed by the user 2026-11-01.

## Method

AHRQ publishes a dedicated page on this exact question, "Using Appropriate Price Indices for
Analyses of Health Care Expenditures or Income Across Multiple Years"
(`https://meps.ahrq.gov/about_meps/Price_Index.shtml`). Two AI web-fetch summaries of this page
disagreed with each other on the headline recommendation, one said GDP, the other said Personal
Health Care Index (PHC) or Personal Consumption Expenditure Health (PCE-Health). The page was
downloaded directly and read as plain text to resolve this, since the index choice is a decision
gate.

Both summaries were partly right, for different objectives the page describes.

## What the page actually says

The page gives different guidance for different objectives, not one single answer.

| Objective | Recommended index |
|---|---|
| Comparing total expenditure levels between two single years (e.g. "how much did societal health spending grow") | GDP price index (or the narrower PCE index) |
| Pooling two or more years of MEPS data into one combined estimate | PCE-Health or PHC |
| **Projecting an expenditure estimate from one year to another year** (e.g. 2014 diabetes spending projected to 2015) | **PCE-Health or PHC** |
| Out-of-pocket expenditure only | CPI, all items, all urban consumers |

Our use case, on-levelling 2022 severity to 2023 prices, then later projecting to the 2026-27
rating period, is the third row. AHRQ's own wording explains why: "health care prices change from
year to year, and faster than overall price inflation, so we need to account for these health
care price changes when pooling." The GDP index is for economy-wide comparisons, and is
explicitly said to be less suitable here because it "includes some expenses extraneous to MEPS
such as those for medical research and public health programs."

## Recommendation

**Use PCE-Health.** AHRQ says PCE-Health and PHC "have tracked very closely over the last two
decades" and treats them as interchangeable for this objective ("use either"). PCE-Health is
recommended here over PHC because it comes from a single public BEA table with no file to
download and parse, while PHC requires downloading and extracting a CMS zip file (Table 23 of the
National Health Expenditure Accounts).

- **PCE-Health source:** Bureau of Economic Analysis, Table 2.5.4 "Price Indexes for Personal
  Consumption Expenditures by Function", Line 37 "Health".
  `https://apps.bea.gov/iTable/iTable.cfm?reqid=19&step=2&isuri=1&1921=survey`
- **PHC source (alternative, not used):** CMS Office of the Actuary, National Health Expenditure
  Accounts, Table 23. `https://www.cms.gov/files/zip/nhe-tables.zip`

Both indices are scaled to 100 in 2017. The exact 2022 and 2023 values will be pulled
programmatically in M2 when the on-level factor is calculated, not hand-copied here, so the
pipeline stays reproducible if AHRQ revises the series.

## Alternatives considered

- **GDP price index:** rejected, it is AHRQ's recommendation for a different objective (comparing
  broad macro expenditure levels), not for projecting or pooling health care costs specifically.
- **CPI-M (medical care component):** rejected, AHRQ says it "only reflects out of pocket
  expenses", not total expenditure, and recommends it only for pooling or projecting out-of-pocket
  amounts specifically.
- **PHC (CMS):** viable alternative to PCE-Health, same recommendation tier, not used only because
  of the extra file-handling overhead.
- **A custom blend of PHC service-type components** (e.g. separate indices for inpatient,
  physician and outpatient facility spend, Table 3 columns 3-11) would more precisely track the
  PMI-scope claim mix, but adds complexity disproportionate to a portfolio project. Noted here as
  a possible refinement if time allows, not pursued for M1/M2.

## Values and factor (added in M2, issue #16)

Downloaded on 2026-11-01 through the BEA API (`uv run --env-file .env python -m
health_pricing.data.price_index`), saved as `data/reference/pce_health.csv` with its checksum and
request in `data/reference/pce_health.meta.json`. The key is read from `BEA_API_KEY` and is never
saved.

| Item | Value |
|---|---|
| PCE-Health index, 2022 | 110.256 |
| PCE-Health index, 2023 | 113.121 |
| On-level factor, 2022 to 2023 prices | 113.121 / 110.256 = 1.02599 |
