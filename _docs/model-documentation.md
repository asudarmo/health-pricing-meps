# Model documentation: v1 tariff

This page is for an actuarial pricing reviewer. It states what the v1 tariff is for, how it was built, what it assumes and where it can
fail. Numbers are the ones in the [README](../README.md) and in the saved tables under `outputs/`, which are the source. Where a number is
not here, the table named beside it holds it.

## Purpose and scope

The model shows how a UK-style private medical insurance (PMI) rating structure can be built from claims data, tested on a later year and
monitored. It is not a UK price. MEPS is a US survey, so costs, benefit design and the mix of people differ from a UK book. The output is
a **risk premium (expected claims cost), illustrative pounds**, which excludes expenses and margin.

## Data

- **Source.** The Medical Expenditure Panel Survey (AHRQ), 2022 and 2023 full-year consolidated files and the event files for inpatient,
  outpatient and office-based care. Downloads are scripted with a size check. Raw and person-level data are not in the repository.
- **Unit.** One row per person-year, 40,210 rows in all, with exposure in years.
- **Claim definition.** A claim is a PMI-scope event. Birth and pregnancy stays are excluded, and so are stays that began in the
  emergency room, because UK emergency admissions are normally NHS. See [`pmi-scope.md`](pmi-scope.md).
- **Time.** 2022 is the modelling year, split by household into training and test. 2023 is the out-of-time year. 2022 costs are
  on-levelled to 2023 prices with the PCE-Health index, committed in `data/reference/`. See [`price-index.md`](price-index.md).
- **Data checks.** dbt tests on the staging and modelling tables, and reconciliation of person counts and weighted totals to AHRQ's
  published figures. See [`data-flow.md`](data-flow.md) and [`data-dictionary.md`](data-dictionary.md).

## Method

- **Technical model.** A two-part model. Frequency is binomial with a complementary log-log link and an offset of log exposure. Severity
  is Gamma with a log link. Annual cost per person-year is capped at 100,000 dollars when fitting, and a flat provisional load of 6.5
  percent adds the capped cost back.
- **Tariff.** A log-link Poisson model fitted to the technical model's predictions, so relativities multiply as a rating table does.
  Adult age is a smooth curve in the technical model and the tariff reads five-year bands off it.
- **Age rule.** The adult age relativities follow a monotone rule, so a premium never falls with age. The bands from 60-64 to 80+ are pooled
  and the base rate is rebalanced so that total predicted cost on the 2022 training split is unchanged.
- **Base rate.** The 2022 base rate carries the forecast trend of 1.019 and the rebase of 1.06 to reach the rating-period level.
- **Premium.** Premium = base rate × product of the relativities × scaling. The scaling is 0.244 pounds per dollar for the illustrative
  pound figure and 1 for dollars.
- **Challenger.** A LightGBM model with household-grouped cross-validation did not beat the GLM and SHAP found no missed interactions, so
  the GLM tariff is the pricing basis.

## Rating factors

Nine permitted factors: age, region and seven condition flags (high blood pressure, coronary heart disease, other heart disease,
cholesterol, cancer, arthritis and asthma). Sex, race, income and education are excluded. Self-rated health, mental health, exercise,
smoking and insurance coverage are fitted as controls and priced at their reference level. The condition flags stand in for the health
information a UK insurer would collect at underwriting. The rating engine rejects the excluded factors with a clear message.

## Performance

| Check | Result | Source |
|---|---|---|
| Test deviance, 2022 split | 839,170, about 9.7 percent below the baseline | `outputs/v1/model_version.json` |
| Gini, 2022 split | 0.376 | `outputs/v1/model_version.json` |
| A/E on 2023 at the rating-period level | 1.080 | `outputs/v1/ae_table.csv` |
| Largest PSI of a rating factor, 2023 | 0.0020 | `outputs/m5_draft/` |

Fitting the tariff to the technical model costs little, with a median approximation error of 0.5 percent by age band. The maximum is 8.2
percent, at 80+ (see Limitations).

## Monitoring and recalibration

The published tables hold A/E by factor and level, PSI by factor, and the validation metrics. The rule in
[`recalibration-rule.md`](recalibration-rule.md) reads them and recommends one of four actions: do nothing, rebase the level, review the
structure or rebuild the model. On 2023 the ranking, the relativities and the mix held, so the gap was a level change and the rule
recommended a rebase.

## Key risks and limitations

- **US data.** The results show the method and not UK prices.
- **One fitting year.** v1 is fitted on 2022. The rebase of 1.06 is a credibility-weighted judgement between one noisy year of own
  experience (+14.5 percent) and an external level change (+2.5 percent), so the 2023 A/E is 1.080 and not 1.00.
- **One out-of-time year.** A one-off change in level cannot be separated from a lasting one.
- **The trend is an assumption.** The 1.9 percent is an external utilisation trend from insurers' rate filings. The A/E and the rebase are
  shown at a low and a high trend.
- **Older ages.** The monotone rule puts the 80+ tariff 8.2 percent above the technical model on the 2022 test split. The likely cause is the
  exclusion of emergency-room-originated stays, which are concentrated at older ages and pull the model's own older-age curve down. This is
  tested only by the sensitivity that adds those stays.
- **Provisional large-claim load.** The flat load of 6.5 percent is from 2022 training data and is not tuned to 2023.
- **Conditions under-predicted.** People with a diagnosed condition were under-predicted by more than the book on 2023.
- **Smoking.** Daily smokers show a lower cost (a relativity of 0.60) in the data. This is not a causal effect, so no discount is applied.
- **Small samples.** The test split and the 2023 year are small with a heavy tail, so intervals are wide.
- **Golden test cases.** They are a regression baseline until the planned Excel reconciliation replaces them.

## What the next version changes

A pooled refit on 2022 and 2023 with a year term, which estimates the level change directly, a projection to a rating period, a
re-estimated large-claim load with an indexed cap, and the Excel reconciliation. See Next steps in the README.

## Reproducing the results

Follow "Reproduce from a clean clone" in the README. The published tables are rebuilt with `uv run python train.py` and checked by
`tests/test_contract_v1.py`.
