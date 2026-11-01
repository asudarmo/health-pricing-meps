# Health Insurance Pricing on MEPS, Phase 1 Modelling Plan

Portfolio project: a UK-style private medical insurance (PMI) pricing exercise built on US MEPS data.
Phase 1 (this plan) is the modelling. Phase 2, a pricing workbench app built on top of this project's
package and outputs, is a separate project and is **out of scope here**, except that Phase 1 must publish
the outputs listed in section 6.

## 1. Why this project

Audience: actuarial pricing reviewers (UK health insurance). The project demonstrates the work of a health
pricing analyst: Python and SQL, practical statistical modelling, and data analysis. Each component maps
to a typical job requirement:

| Job ad requirement | Project component |
|---|---|
| Rebuild/develop risk models (GLM and ML) for claim frequency and severity | Poisson/negative binomial frequency GLM, Gamma (or lognormal) severity GLM, Tweedie pure premium, gradient-boosted alternative |
| Data preparation, cleansing, validation, feature engineering, reasonableness checks | Reuse the claims project's validation pattern (checks, quarantine, logged exclusions) |
| Monitor model performance: actual vs expected, rating factor reviews, drift | A/E by rating factor and over time, population stability index (PSI) drift checks, recalibration triggers |
| Rate change impact analysis | Dislocation analysis of a proposed rate change by segment |
| Prepare data for conversion and elasticity modelling | Simple logistic conversion model on simulated quotes, price elasticity curves |
| Document assumptions, risks and limitations | Model documentation section in the README / report |
| Automate manual Excel processes using Python, SQL and AI | Re-implement a small Excel rating/A-vs-E workbook as a tested Python pipeline · show AI-assisted coding with checks |
| Present analysis to stakeholders | Short written summary + a few clear charts (optionally a small dashboard) |

## 2. Data decision (decided 31 Oct 2026): MEPS

**Use the US Medical Expenditure Panel Survey (MEPS), Household Component, Full-Year Consolidated file.**
Years (corrected 31 Oct): fit on 2022 (HC-243), validate out-of-time on 2023 (HC-251, released Aug 2025),
then refit on 2022 + 2023 pooled for the final factors. Optional: add 2019 as a pre-COVID year if claimant
counts are thin. Exclude 2020–21 (COVID distorted utilisation). Design details in section 2.5.
Source: https://meps.ahrq.gov/data_stats/download_data/pufs/h251/h251doc.shtml
(IPUMS MEPS, https://meps.ipums.org, offers harmonised variables across years. It is an easier option for
combining 2022 and 2023.)

### 2.1 What MEPS is

- Run by AHRQ. Nationally representative survey of health care use, spending, payment source and insurance
  for the US civilian non-institutionalised population. Households are interviewed five times over two
  calendar years. A new panel starts each year.
- A Medical Provider Component contacts a sample of respondents' providers and is used to impute/replace
  household-reported spending, so costs are close to real paid amounts. "Expenditure" = payments from all
  sources, not billed charges (the right basis for pricing).
- 2023 FYC: 18,919 persons (18,463 with a positive person weight), 1,374 variables. Formats: ASCII with
  SAS/Stata/SPSS/R load scripts, SAS, Stata, Excel.
- Companion event files (inpatient stays, outpatient, office-based, ER, prescribed medicines, etc.), one
  record per event, linkable on `DUPERSID`. These give true per-claim severity.
- Licence: statistical analysis and reporting only, no re-identification attempts, cite AHRQ/MEPS as source.
  A portfolio pricing model is within these terms.

### 2.2 Data dictionary: variables that matter (verify names against the 2023 codebook)

| Pricing role | MEPS variables |
|---|---|
| Rating factors | `AGE23X` (top-coded 85), `SEX`, `REGION23`, perceived health `RTHLTH*`, priority conditions (`HIBPDX`, diabetes, heart disease, cancer, asthma, arthritis), BMI and smoking (adult self-completion questionnaire), `INSCOV23` |
| Frequency | counts of office-based, outpatient, ER visits · inpatient discharges and nights · prescriptions |
| Severity | `TOTEXP23`, split by service type and payer (self, private, Medicare, Medicaid) · per-event cost from event files |
| Exposure | part-year persons (births, deaths, institutionalisation): use months in scope as the exposure offset |
| Survey design | `PERWT23F`, variance strata/PSU |

Traps for the validation layer:

- Reserved negative codes (-1 inapplicable, -7 refused, -8 don't know, -15 cannot be computed) must become nulls
- Age is top-coded at 85
- Suffix "23" means status at 31 Dec 2023, while "_M23" means the question changed in 2023
- Variable names change suffix by year (22 vs 23)

### 2.3 Options considered and rejected

- **UK data:** no free UK person-level dataset combines health status and costs (NHS care isn't paid per
  person, and PMI claims are proprietary). CPRD + HES with NHS unit costs is the gold standard but needs a
  licence, organisational approval and fees. CPRD synthetic samples have no costs and need a request form.
  NHS England artificial HES keeps structure only and is explicitly not suitable for modelling. Simulacrum
  is cancer-only, no costs. Health Survey for England, Understanding Society and ELSA (UK Data Service)
  have health/BMI/smoking but no spending. They are a possible stretch source for reweighting MEPS to UK demographics.
- **CMS Marketplace PUFs (my existing project, `C:\Users\ardih\Data\CMS_Health_Insurance_Exchange`):**
  ACA individual-market filed premiums (Rate file) and benefit design (Plan Attributes), not Medicare and
  not claims. ACA modified community rating allows only age (federal curve, 3:1), tobacco (1.5:1), area and
  family composition, so the derived age/tobacco factors are largely regulatory, not estimated risk. Cannot
  support frequency/severity models. Still useful in three ways. (a) A separate portfolio piece on benefit-design
  pricing (maps to UK PMI excess/limits/hospital lists). (b) A real market-price benchmark for the
  conversion/elasticity step (optional). (c) The URR rate-review PUFs hold plan/issuer-level premiums,
  incurred claims and member months, for aggregate loss-ratio/A-vs-E work (not used here).
- **freMTPL2 (French motor):** standard GLM-vs-GBM benchmark, but not health. Not needed.

### 2.4 How MEPS is made to feel like UK PMI (state this plainly in the README)

1. Define "claims" as services UK PMI typically covers: inpatient (incl. day-case) stays and hospital
   outpatient/specialist care and diagnostics. Exclude routine GP, ER and most prescriptions (NHS-covered).
   Check whether office-based events can be split by provider specialty. If not, document the proxy used.
   The starting definition and its rationale are in section 2.4.1.
2. Report rating factors as relativities (age curve, condition and smoker loadings), not dollar levels.
3. Simulated UK product layer (excess, outpatient limit, underwriting type) for rate-change and conversion.
4. Conduct: build the analysis with sex, but exclude it from the final rating structure (UK gender-neutral
   pricing) and show the impact. Do not use race, income or education as rating factors. Condition flags
   mimic full medical underwriting. Note the moratorium alternative.
5. Survey weights: fit models unweighted on exposure, as an insurer would on its own book. Use `PERWT23F`
   only for population sanity checks.

### 2.4.1 PMI-scope claims (starting position for decision gate 2)

**What "PMI-scope" means.** MEPS records all of a person's health care. A UK private medical insurance
(PMI) policy pays for only part of it, because the NHS provides the rest. "PMI-scope claims" are the MEPS
events a UK PMI insurer would typically pay for. Only these count as claims in the frequency, severity and
pure premium models. The final definition is set at decision gate 2 (`AGENTS.md`), based on the evidence
tables, and recorded in `_docs/decisions.md`. This section is the starting position, not the decision.

| MEPS event type | Typical UK PMI treatment | Starting position |
|---|---|---|
| Inpatient stays (incl. day-case) | Core PMI benefit | In |
| Hospital outpatient department | Specialist consultations · diagnostics · scans | In |
| Office-based visit, specialist physician | Private consultant appointment | In |
| Office-based visit, GP or primary care | NHS GP | Out |
| ER visit | NHS A&E | Out (an admission that follows still counts as inpatient) |
| Prescribed medicines | Mostly NHS prescriptions | Out (drugs given during a stay are already in inpatient cost) |
| Dental, optical, home health | Excluded or separate add-ons | Out |

Guidance for the evidence review at the gate:

- **Provider specialty (`DRSPLTY_M18`).** Family or general practice, general internal medicine and general
  paediatrics act as US primary care, so they are out. Clear specialties (cardiology, orthopaedics,
  dermatology, oncology and similar) are in.
- **Visit category (`VSTCTGRY`).** Routine check-ups, immunisations and well-child visits are out, because
  PMI does not cover preventive care. Pregnancy and maternity care is out, as it is usually excluded from
  UK PMI. Diagnosis or treatment visits and follow-ups with specialists are in.
- **Grey areas, decided explicitly at the gate rather than by default.** Non-physician providers such as
  physiotherapists and psychologists (many policies cover therapies with limits), and psychiatric care
  (often covered with limits).
- **Sense check.** The definition should capture a clear minority to moderate share of total spending,
  because prescriptions, ER, primary care and dental are excluded. A share close to 100% or close to 0%
  signals a mistake.

Known limitation (state it in the README rather than modelling it): real PMI also excludes cover by
condition, such as chronic conditions and pre-existing conditions under a moratorium. MEPS cannot model
this cleanly, so the PMI scope here is defined by event type, provider and visit category only.

### 2.5 Time periods, trend and validation design (added 31 Oct 2026)

Industry context: general insurance often fits risk factors on 3–5 years. Health pricing typically uses
2–3 years because claims settle quickly but costs and treatment patterns change fast. Relativities can use
more years. The overall cost level comes from the most recent experience, projected forward. Two years is
on the short side but realistic for a health book. Say so in the README.

Validation goes forward in time, as in real pricing:
1. **Fit on 2022.** Within 2022, hold out a test set split by household (`DUID`), not by row.
2. **Out-of-time test on 2023.** MEPS households stay in the survey two years, so many people appear in both
   2022 and 2023 (like renewing customers). This is acceptable for the out-of-time test but must be stated,
   and any within-year split must be grouped by household.
3. **Final model:** refit on 2022 + 2023 pooled with a year term, so other factors are estimated net of trend.

Trend adjustment, split into its two parts:
- **Severity (cost per claim):** on-level 2022 costs to 2023 prices with a published medical price index.
  Use the index AHRQ's MEPS documentation recommends for comparing expenditure across years (check in M1).
- **Frequency (claims per person):** estimate from the data (year term in the pooled GLM). For the
  out-of-time test, apply an assumed frequency trend and state it.

Judging the out-of-time test (keep the three separate):
- **Ranking:** Gini, lift and double-lift charts (unaffected by trend).
- **Relativity stability:** refit on 2023 and compare the age curve, condition and smoker loadings.
- **Level:** overall and by-factor A/E after the trend adjustment. The remaining gap is trend-estimate error.
  This supports the "recalibrate the level, keep the structure" decision.

Projection for pricing: trend factor = (1 + annual trend) ^ (years from the midpoint of the experience period
to the midpoint of the rating period), e.g. 2022–23 data projected to policies written in 2026–27.

## 3. Modelling plan

1. **Data pipeline:** load MEPS raw files → SQL (DuckDB + dbt) staging → validation checks (types, ranges,
   duplicates, missing, outliers) with logged exclusions → modelling table. pytest for key transforms.
2. **Frequency:** Poisson GLM with exposure offset. Check over-dispersion → negative binomial if needed.
3. **Severity:** Gamma GLM (log link) on claimants. Consider capping large claims and a separate large-claim load.
4. **Pure premium:** frequency × severity, and a Tweedie GLM as a single-model comparison.
5. **Machine learning challenger:** LightGBM/XGBoost (Poisson/Gamma/Tweedie objectives, monotonic constraints
   where sensible), SHAP for explanation, compared on the household-grouped 2022 hold-out and the 2023 out-of-time year (deviance, Gini/lift,
   double-lift chart).
6. **Monitoring:** A/E by factor and by period, PSI on key factors, and a simple "recalibration needed" rule.
7. **Rate change impact:** apply a proposed change and show the distribution of premium changes by segment (dislocation),
   with caps/floors discussion.
8. **Conversion and elasticity:** logistic model of take-up vs price relative to a benchmark on simulated
   quotes, elasticity by segment, and a note on the link to fair-pricing / Consumer Duty considerations.
9. **Excel automation story:** small Excel workbook doing an A/E or rating calculation by hand → Python
   version reproducing the same numbers (regression test), then extended.

Tools: Python (pandas/polars, statsmodels, scikit-learn, LightGBM, SHAP), SQL (DuckDB/Postgres), pytest,
MLflow for experiment tracking (optional), Excel. Optional: run on Databricks to reuse DP-750 skills.

## 4. Deliverables

- GitHub repo with README (problem, data, approach, results, limitations), reproducible pipeline, tests.
- A short report/notebook with the key charts: A/E by factor, lift/double-lift, SHAP summary,
  dislocation histogram, elasticity curve.
- Published, versioned output tables and an installable pricing package (see section 6).

## 5. Milestones

Repo: new GitHub repo `health-pricing-meps` (name TBC). Stack: Python (uv), DuckDB + dbt (the CMS project at
`C:\Users\ardih\Data\CMS_Health_Insurance_Exchange` may be read for reference, never modified),
polars/pandas, statsmodels, LightGBM, SHAP, pytest, MLflow (optional), Excel. Every session ends with
tests passing and a short entry in `_docs/log.md`.

Code structure (decided 31 Oct): notebooks for prototyping and explaining each modelling step, alongside
(1) an installable Python pricing package (a rating engine that turns a profile into a premium with its
factor breakdown, and a scenario into its impact) with no notebook dependencies, and (2) every output saved as tidy, versioned tables
(relativities, A/E, PSI, aggregated in-force book, model_version.json, golden test cases). These are the
inputs Phase 2 needs (see section 6).

The work is organised as milestones M1–M9, not dates, although the MVP is expected to complete in 1 week. The MVP is M1–M7 and M9. M8 and the stretch goals
are optional (see the cut order below). Each milestone is broken into numbered tasks
(`_docs/tasks.md`, then GitHub issues assigned to the matching GitHub milestone). Work pauses at the end of
each milestone for the user's review. A milestone may start once the milestones it depends on are done.

| Milestone | Scope | Deliverables | Done when | Depends on |
|---|---|---|---|---|
| M1 Setup and data | Repo, tooling, raw data | Repo skeleton (uv, pytest, dbt, DuckDB) · writing-style check test · scripted download of 2022 and 2023 FYC + inpatient/outpatient/office-based event files · variable shortlist and 2022↔2023 name mapping from codebooks · check whether office-based events record provider specialty · confirm AHRQ's recommended price index · raw → DuckDB staging | Raw row counts match documentation for both years (18,919 persons in 2023) · mapping reviewed at decision gate | None |
| M2 Validation and modelling table | Clean, validated, one row per person-year | Value-level rules per variable in dbt `schema.yml` (valid values or ranges plus the allowed reserved codes) · treatment of each reserved code in the staging SQL (e.g. -1 on adult-only flags for children → "not applicable", -7/-8/-15 → null, age 85 kept), logged in `_docs/decisions.md` · range/type/duplicate checks with logged exclusions and quarantine · exposure (months in scope) · PMI-scope claim counts and costs per person for both years · 2022 costs on-levelled to 2023 prices · household-grouped train/test split within 2022 · reconciliation to AHRQ published summary tables · pytest on transforms · EDA notebook | One row per person-year with exposure, rating factors, claim count, claim cost · every exclusion logged · weighted totals reconcile to published figures · dbt build passes with zero values outside the declared rules · unweighted value counts for key variables (age, sex, region, condition flags, smoking, RTHLTH) match the AHRQ codebook | M1 |
| M3 GLMs | Frequency and severity | On the 2022 training split: Poisson frequency GLM with log(exposure) offset, over-dispersion test → negative binomial if needed · Gamma log-link severity GLM on claimants with large-claim cap and separate load · relativity tables · GLM notebook | Coefficients sensible · residual and A/E-by-factor checks reasonable · relativities saved as tables | M2 |
| M4 Pure premium and ML challenger | Model comparison | Tweedie GLM · LightGBM (Poisson/Gamma/Tweedie objectives, monotone age constraint) with SHAP · comparison on the 2022 household-grouped hold-out: deviance, Gini, lift and double-lift charts · how GBM insights feed back into the GLM | Comparison table and charts saved · model choice made at decision gate | M3 |
| M5 Out-of-time test and monitoring | Forward validation on 2023 | Trend-adjusted 2022 model predicts 2023: ranking (Gini, double lift), relativity stability (refit on 2023 and compare), A/E overall and by factor after trend · PSI drift · recalibration rule · low/high trend sensitivity | A/E, relativity-stability and PSI tables saved · recalibration rule documented | M3 (M4 for the chosen model) |
| M6 Final model, rating engine and rate change | Publishable v1 | Final refit on 2022 + 2023 with year term, projected to the rating period · rating engine in the package (profile → premium with breakdown) · aggregated in-force book · scenario impact (base change, relativity changes, caps/floors) → dislocation by segment · publish `outputs/v1/` per section 6 | All section 6 outputs exist and are tested · dislocation histogram saved | M4, M5 |
| M7 Excel reconciliation | Excel-to-Python automation story | Small Excel rating/A-E workbook built by hand · Python reproduces it · golden test cases (profiles → expected premiums) | Python matches Excel to the penny · golden tests pass in CI/pytest | M6 |
| M8 Conversion and elasticity | Demand side | Simulated quotes from a known price-response curve · logistic conversion model · elasticity by segment · recovered vs true parameters · fair-pricing note | Elasticity recovers the simulated truth within stated tolerance | M6 |
| M9 Write-up | Reviewer-ready repo | README (problem, data, UK translation, time periods and trend assumptions, method, results, limitations) · model documentation (assumptions, risks, limitations) · key charts · notebooks run top to bottom | A reviewer can reproduce results from a clean clone using the README | M1–M8 |

M7 and M8 are independent of each other and can run in either order once M6 is done.

### Priority and cut order

If time runs short, cut in this order:

1. Stretch goals (below)
2. M8 Conversion and elasticity (keep a short note of the intended approach)
3. M4 scope: one LightGBM objective instead of three

Never cut: M2 validation and reconciliation, M5 out-of-time test, the M6 published outputs (section 6),
and M7 golden tests (Phase 2 depends on them).

Stretch (only if ahead):

- Add 2019 as a pre-COVID year
- Reweight MEPS to UK age/sex/BMI/smoking mix (Health Survey for England)
- Databricks run
- CMS market rates as a conversion benchmark
- BMI sensitivity analysis on 2022 only, BMI has no 2023 equivalent so cannot be validated
  out-of-time (`_docs/variable-mapping.md`)

### Risks

- 2022 vs 2023 variable naming (use IPUMS or a mapping table)
- Small claimant counts for severity in thin segments (group levels, credibility-weight, or add 2019)
- The same people in both years (state it, and group splits by household)
- Trend assumption sensitivity (show results under a low and high trend)

## 6. Outputs Phase 2 depends on (the contract)

Phase 1 must publish these, so the app can be built without touching the modelling code:

- **Pricing package** (installable, under `src/`): a function that takes a customer profile and a model
  version and returns the premium with its factor-by-factor breakdown (base rate × each relativity), and a
  function that applies a rate-change scenario (base change, relativity changes, caps/floors) to an
  aggregated in-force table and returns the impact.
- **Model version metadata** (`model_version.json`): id, date, data years, trend assumptions, validation
  metrics (deviance, Gini), permitted rating factors.
- **Relativities table:** factor, level, relativity, exposure, lower and upper confidence bounds.
- **Base rate**, plus the UK scaling assumption used for illustrative £ premiums.
- **A/E table:** factor, level, segment, period, actual, expected, exposure.
- **PSI table:** factor, period, PSI value.
- **Aggregated in-force book:** exposure by rating cell, for scenario impact.
- **Golden test cases:** profiles with expected premiums (from the Excel reconciliation).

All published tables are aggregated. No person-level MEPS records are published.
