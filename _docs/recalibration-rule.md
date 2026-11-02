# Recalibration rule: a change of level or a change of structure

This is the rule of issue #47. It reads the evidence of the out-of-time test and recommends one of four actions. It does not change
the model. The final refit is M6. The code is `src/health_pricing/models/recalibration.py` and the thresholds below are its constants.

## Evidence the rule reads

| Evidence | Source table | Used as |
|---|---|---|
| Overall A/E and its household interval | `ae_overall_2023.csv` | `gap`: the interval excludes 1 |
| Wald test that the frequency and severity relativities are unchanged | `stability_joint_tests.csv` | `structure_moved` if either p-value is below 0.05 |
| Rating levels whose 2023 to 2022 ratio excludes 1, out of those compared | `stability_beyond_noise.csv` | `structure_moved` if more than chance gives (binomial p below 0.05, with 5 percent per level) |
| Rating levels whose relative A/E excludes 1, out of those with 30 claimants | `ae_by_level_2023.csv` | `structure_moved` on the same chance test |
| Largest PSI of a rating factor or of predicted cost | `drift_psi_*.csv` | `mix_moved` if above 0.1 |
| Gini on 2023 against the 2022 test split | `scores_2023.csv`, `frozen_model_scores_2022.csv` | `ranking_lost` if lower by more than 0.05 |

The decomposition of the gap into mix, frequency, severity and large claims is read alongside, and the rule reports it, but it
is not a threshold. The large-claim load is handled apart. It is re-estimated in M6, and the rule reports the A/E points that
matching the load to 2023 would add.

## Actions

| Condition | Action | What follows |
|---|---|---|
| No gap, and `structure_moved` false | Do nothing | Keep monitoring |
| Gap, `structure_moved` false | Rebase | Change the base rate by a credibility-weighted factor, and keep the relativities |
| `structure_moved` true, `ranking_lost` false | Refit the relativities | Refit with pooled years in M6 |
| `structure_moved` true, `ranking_lost` true | Review the structure | The factors or the form of the model need review before any refit |

A change of mix (`mix_moved`) is reported with the action. With stable relativities it does not change a rebase, because the
balance of the base rate is recomputed on the new mix. With moved relativities it adds weight to refitting with pooled years.

## Credibility of one year

A rebase does not move the base rate by the full A/E. Two weights are reported.

- **Sampling credibility.** The square-root rule of limited fluctuation, with full credibility at the claimants needed to be within 5
  percent of the true level with a probability of 90 percent, for a Poisson claim count and the observed severity variation. The
  standard is 1,082 times (1 plus the squared coefficient of variation of capped cost per claimant). It measures sampling error only.
- **Persistence credibility.** The Buhlmann weight `spread^2 / (spread^2 + standard error^2)`, where the standard error is that of the
  A/E and the spread is the year-to-year change in level that the forecast allows. The spread is 1.7 percent, which is the quartile
  range of the CMS utilization trend (0.8 to 3.1 percent) read as a normal spread. It is a lower bound, because two years of data
  cannot estimate how much the level drifts, and a tight spread gives little weight to any large gap.

The rule reports the base-rate factor at both weights and does not choose within the range. The choice is a judgement for the
user. A pooled refit of both years in M6 weights the two years about equally, which sits inside the range.

## Application to the 2023 evidence

See the section "Recalibration rule" of `notebooks/04_monitoring.ipynb`, which applies the rule to the saved tables.
