# UK-style health insurance pricing on MEPS: GLMs, out-of-time monitoring and a GBM challenger

## Key results

- **Final tariff.** 9 UK-permitted rating factors, a test deviance 9.7 percent below the baseline and a Gini of 0.378.
- **Out-of-time 2023.** A/E of 1.145, but the ranking, the relativities and the mix held, so it is a **level change and not a structure
  change**. A credibility-weighted rebase of 1.06.
- **GBM challenger.** LightGBM with cross-validation grouped by household did not beat the GLM, and SHAP found no missed
  interactions, so the **GLM tariff is the pricing basis**.
- **Judgement calls.** A smoker discount (a relativity of 0.60 for daily smokers) was found in the data, investigated and not priced.
  Exercise showed a raw 31 percent cost gap but no clear effect after adjustment (0.97 on frequency and 1.07 on severity).
- **Stack.** Python, SQL (DuckDB and dbt), statsmodels, LightGBM, SHAP and pytest.

A UK-style private medical insurance (PMI) pricing exercise built on US MEPS survey data. This is the **interim README**. The data
pipeline, the frequency and severity GLMs, the final tariff, the out-of-time test and monitoring on 2023 and the GBM challenger
(M4, lite) are done. The final rating engine, the Excel reconciliation and the model service are in progress (see
[Roadmap](#roadmap-in-progress)). The full plan is in [`_docs/plan.md`](_docs/plan.md), the decisions are in
[`_docs/decisions.md`](_docs/decisions.md) and the data flow is in [`_docs/data-flow.md`](_docs/data-flow.md).

The audience is an actuarial pricing reviewer. The full notebooks explain each step and are `03_glm.ipynb`, `04_monitoring.ipynb` and
`05_gbm.ipynb`. The short versions, which only load saved tables and charts, are
[`notebooks/03_glm_summary.ipynb`](notebooks/03_glm_summary.ipynb),
[`notebooks/04_monitoring_summary.ipynb`](notebooks/04_monitoring_summary.ipynb) and
[`notebooks/05_gbm_summary.ipynb`](notebooks/05_gbm_summary.ipynb). Every number below is read from a saved table under `outputs/`.

## How this was built

This project was built with an AI coding agent working from a written spec, with decision gates where I made the modelling calls,
automated tests, a separate QA review of each task and a decision log. The agent does the implementation, and every modelling or data
choice is recorded with its evidence and alternatives. See [`AGENTS.md`](AGENTS.md), [`_docs/process.md`](_docs/process.md) and
[`_docs/decisions.md`](_docs/decisions.md).

## The problem

A UK private medical insurer prices each policy from a base rate and a small set of rating factors. This project builds that
rating structure from claims data, tests it on a later year, and monitors it as a pricing team would: actual against expected cost
(A/E), stability of the relativities, drift in the mix of people, and a rule for when to change the level or the structure.

## The data and the UK framing

The data are the Medical Expenditure Panel Survey (MEPS) of the US Agency for Healthcare Research and Quality (AHRQ): the 2022 and
2023 full-year consolidated files and the event files for inpatient stays, outpatient visits and office-based visits. There is no
UK claims data of this kind in the public domain, so MEPS is used to show the method.

- **Claims.** A claim is a PMI-scope event: stays and visits that a UK private medical policy would normally pay for, with
  stays that began in the emergency room left out of the base definition. See [`_docs/pmi-scope.md`](_docs/pmi-scope.md).
- **Time.** 2022 is the modelling year, split by household into a training and a test split. 2023 is the out-of-time year. 2022 costs
  are on-levelled to 2023 prices with the PCE-Health index.
- **Rating factors.** The final structure uses only factors a UK insurer could use. Sex, race, income and education are excluded.
- **People.** The modelling table has one row per person-year (40,210 in all), with exposure in years.

Raw MEPS files and person-level data are not in the repository. Published outputs are aggregates only. MEPS data are used for
statistical analysis and reporting only, with no attempt to identify individuals. Source: AHRQ / MEPS, https://meps.ahrq.gov.

![Data flow](outputs/figures/diagrams/diagram_1.svg)

## Method

**Two-part model.** Expected annual cost is the chance of a claim times the expected cost of a claimant. The chosen model, (a), has a
binomial frequency part with a complementary log-log link and an offset of log exposure, and a Gamma severity part with a log link.
Candidate (b) has a Poisson frequency part, which makes it exactly multiplicative, and candidate (c) is stacked by benefit type. Both
were close to (a) on the test split and were not chosen. The models are compared on the 2022 test split with the Tweedie deviance
(power 1.5), the exposure-weighted Gini, lift and double-lift charts and A/E. The full table of every candidate is in
[`notebooks/03_glm_summary.ipynb`](notebooks/03_glm_summary.ipynb).

| Model | Frequency part | Severity part | Expected annual cost | Multiplicative | Parameters |
|---|---|---|---|---|---|
| (a) Binomial-cloglog × Gamma | Binomial, cloglog, offset $\log t_i$ | Gamma, log | $p_i\,\mu_i\,(1+\ell)$ | No, the claim chance cannot exceed 1 | 88 |
| (a) Final structure with a smooth age curve | Binomial, cloglog, age spline | Gamma, log, age spline | $\rho\,p_i\,\mu_i\,(1+\ell)$ | No | 64 |
| (a) Final tariff | None, a Poisson-log model of the smooth age model's cost | None | $t_i\,r_0\prod_k r_{k,\,l_k(i)}$ | Yes | 26 |

The first row has all 18 candidate factors and the other two have the 9 rating factors and 5 analysis-only controls. A parameter is a
coefficient of the frequency part plus a coefficient of the severity part, and the dispersion is not counted. Here $t_i$ is the
exposure of person-year $i$ in years, $p_i$ is its chance of a claim, $\mu_i$ is the expected cost of a claimant, $\ell$ is the
provisional large-claim load, $\rho$ is the balance factor that makes predicted cost equal actual cost on 2022 train, $r_0$ is the base
rate per year of exposure, $l_k(i)$ is the level of rating factor $k$ for person-year $i$ and $r_{k,l}$ is the relativity of level $l$
of factor $k$.

**Large claims.** Annual cost per person-year is capped at 100,000 dollars when fitting. In train, 32 claimants are above the cap and
6.1 percent of train cost is above it. A flat provisional load of 6.5 percent adds it back. Costs are scored uncapped. The load is
re-estimated in M6.

**Factors.** The final structure has 9 rating factors: age, region and seven condition flags (high blood pressure, coronary heart
disease, other heart disease, cholesterol, cancer, arthritis and asthma). Four condition flags were dropped by a selection rule.
Self-rated health, mental health, exercise, insurance coverage (`inscov`) and smoking are fitted as controls and priced at their
reference level, so they are analysis-only. Smoking has a relativity of 0.60 for daily smokers, which is not
a causal effect, so no smoker discount is applied. Removing the condition flags barely moves it (0.60), so the flags do not explain it,
and the pattern is consistent with US differences in access to and use of care. Adult age is a smooth curve (a natural spline) and the tariff reads
five-year bands off it. The condition flags stand in for the health information a UK insurer would collect at underwriting.

**Final tariff.** A multiplicative model with 26 parameters, fitted to the predictions of the smooth model, so
that relativities multiply as a rating table does. On the 2022 test split its deviance is 838,173 (9.7 percent below the baseline), its Gini is
0.378 and its A/E is 1.081. The technical model (the unrounded structure) is what the out-of-time test scores
alongside it.

## Results

### Models on the 2022 test split

- Candidate (a) with all factors has a test deviance of 808,193 (12.9 percent below the baseline) and a Gini of 0.433.
  Candidate (b) is close, with a deviance of 816,054 (12.1 percent below the baseline). The surrogate model (tariff)
  of (a) has 814,292 (12.3 percent below the baseline), so the multiplicative form costs little.
- The final structure with 9 factors has a deviance of 830,232 (10.6 percent below the baseline) and a Gini of 0.393.

![Lift of the final tariff](outputs/m3_draft/figures/lift_final_tariff.png)

![Relativities of the final structure](outputs/m3_draft/figures/relativities_final.png)

### Out-of-time test on 2023

The model is frozen on 2022 and scored on 2023, which no earlier step used. The forecast trend is the CMS Unified Rate Review median
utilization trend of 1.9 percent, set before looking at 2023.

| Question | Result |
|---|---|
| A/E, technical model | 1.145 (1.075 to 1.220) |
| A/E, tariff | 1.145 (1.074 to 1.220) |
| Gini, technical model and tariff | 0.473 and 0.468 |
| Rise in cost per exposure year | 16.9 percent, of which severity beyond the price index 13.9 percent (5.6 to 23.0) |
| Relativities stable? | Wald test p of 0.64 (frequency) and 0.27 (severity), 1 of 13 rating levels beyond noise |
| Mix of people moved? | Largest PSI 0.0020, far below 0.1 |
| Rebase | 1.06 on the forecast cost, with bounds of 1.025 and 1.145 |
| Trend sensitivity | A/E of 1.158 and 1.132 at the low and high trend, the same action |
| ER-originated stays added | Cost rises by 33.0 percent, A/E of 1.523 for the base model and 1.147 for the refit on the broadened cost |

The Gini on 2023 and on the 2022 test split are not directly comparable, because they come from different people and years. The
ranking holds on 2023 and the relativities and the mix do not move, so the gap is a **change of level and not of structure**.
It is mostly severity beyond the price index, read as intensity. The recalibration rule recommends a rebase, and the factor of 1.06
weights one noisy year of own experience (+14.5 percent) with an external level change (+2.5 percent). The M6 pooled refit with a
year term estimates the level directly and supersedes it. People with a diagnosed condition were under-predicted by more than the
book, which is a pattern to watch. The rule is in [`_docs/recalibration-rule.md`](_docs/recalibration-rule.md).

![Lift on 2023](outputs/m5_draft/figures/lift_2023.png)

![Relativity stability](outputs/m5_draft/figures/relativity_stability_2023.png)

![PSI drift](outputs/m5_draft/figures/drift_psi_2023.png)

![Trend sensitivity](outputs/m5_draft/figures/trend_sensitivity_2023.png)

How the evidence is produced and read:

![Monitoring workflow](outputs/figures/diagrams/diagram_5a.svg)

![Level or structure](outputs/figures/diagrams/diagram_5b.svg)

### Gradient-boosting challenger (M4-lite)

A LightGBM model with a Tweedie objective, log exposure as an offset and five-fold cross-validation grouped by household did not beat
the GLM on the 2022 holdout. Its test deviance is 840,754 against 838,173 for the GLM tariff and 831,786 for the technical model, with
a Gini of 0.378 for both the GBM and the GLM tariff (0.386 for the technical model), and the gaps are within noise. Its surrogate
tariff is worse than the GLM tariff, with a deviance of 843,827 and a Gini of 0.368. SHAP found no interaction among the rating factors
that the GLM misses. On 2023 the Gini is 0.469 for the GBM, 0.460 for its tariff and 0.468 for the GLM tariff, and the GBM deviance is
0.6 percent below the GLM tariff's but its own tariff is above it. The GBM is constrained to rise with adult age, as UK premiums do,
and a diagnostic refit without the constraint was no better (deviance 843,561, Gini 0.372). **The GLM tariff is the pricing basis.**
The short version is [`notebooks/05_gbm_summary.ipynb`](notebooks/05_gbm_summary.ipynb) and the full one is `notebooks/05_gbm.ipynb`.

## Limitations

- **US data.** MEPS is a US survey. Costs, benefit design and the mix of people differ from a UK book, so the results show the
  method and not UK prices.
- **Small, heavy-tailed samples.** The 2022 test split and the 2023 year are small with a heavy tail, so intervals are wide and
  level-by-level A/E flags are noted and not tuned.
- **Provisional large-claim load.** The load of 6.5 percent is from 2022 train and is not tuned to 2023. It is re-estimated in M6.
- **Conditions stand in for underwriting.** The condition flags are a proxy for underwriting information, and the A/E by level
  shows a pattern for them that is worth watching.
- **Smoking.** Smoking is analysis-only and no discount or loading is applied.
- **Older ages.** The tariff's age curve flattens after about 60 and falls from the 65-69 band (the 80+ relativity is 0.887 against
  1.000 at 65-69). One likely reason is that the PMI scope leaves out stays that began in the emergency room, which are concentrated at
  older ages (they add 39.0 percent to cost at 65 and over against 24.8 percent at 18 to 39). The ER sensitivity points the same way
  but does not settle it. With the stays added, the age curve is higher at old ages (the relativity at 80 against 67 is 0.983 against
  0.870 and at 85 it is 0.947 against 0.782), yet the interval of the ratio contains 1 at every age. A UK implementation would
  calibrate older-age relativities to UK market experience. The monotone adult age rule drafted for M6 (issue #57) removes the fall
  in the meantime.
- **The trend is an assumption.** The 1.9 percent is an external utilization trend from insurers' rate filings. The A/E and the rebase are
  shown at a low and a high trend.
- **One out-of-time year.** A one-off change in level cannot be separated from a lasting one with one year of data.

## Roadmap (in progress)

| Milestone | What it will add | Reruns |
|---|---|---|
| M4 Pure premium and ML challenger | Done (lite): the LightGBM challenger with SHAP, grouped cross-validation and its surrogate tariff, with the GLM tariff kept as the pricing basis. A Tweedie GLM and a GBM with the health and exercise controls are optional and not run | Nothing, because M4 did not change the chosen model |
| M6 Final model, rating engine and rate change | A final refit on 2022 and 2023 with a year term, a re-estimated large-claim load and indexed cap, a rating engine, the in-force book and rate-change impact. It also adopts the monotone adult age rule (issue #57, drafted in `outputs/m6_draft/`), an isotonic adjustment of the adult band relativities followed by a rebalance | Supersedes the 1.06 rebase |
| M7 Excel reconciliation | A small Excel rating workbook that Python reproduces to the penny, with golden test cases | |
| M10 Model serving | A FastAPI service for quotes, relativities and monitoring, serving the published outputs | |

## Reproduce from a clean clone

The raw files are downloaded by script and are not committed.

```
uv sync
uv run python -m health_pricing.data.download
uv run python -m health_pricing.data.load
uv run dbt deps --project-dir dbt --profiles-dir dbt
uv run dbt build --project-dir dbt --profiles-dir dbt
uv run pytest
uv run python -m health_pricing.data.urr
uv run python -m health_pricing.diagrams
uv run jupyter lab
```

Open the notebooks in order: `01_data.ipynb`, `02_eda.ipynb`, `03_glm.ipynb`, `04_monitoring.ipynb` and `05_gbm.ipynb`. The summary
notebooks `03_glm_summary.ipynb`, `04_monitoring_summary.ipynb` and `05_gbm_summary.ipynb` only read saved tables and charts. Seeds are fixed, so the results reproduce.

## Licence note

MEPS data is used for statistical analysis and reporting only, with no attempt to identify individuals. Source: AHRQ / MEPS,
https://meps.ahrq.gov.
