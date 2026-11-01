# Reconciliation to AHRQ published figures

Issue #19. The data layer is checked against figures AHRQ publishes. Every figure is in
`tests/data/published_figures.csv` with its source and location, and `tests/test_reconciliation.py`
compares it with the data. Weights are used for these sanity checks only, models are fitted
unweighted.

## Results

| Check | 2022 | 2023 | Source |
|---|---|---|---|
| Persons on the file | 22,431, ours 22,431 | 18,919, ours 18,919 | HC-243 and HC-251 documentation, opening paragraph |
| Persons with a positive weight | 21,747, ours 21,747 | 18,463, ours 18,463 | Same paragraph. The modelling table has the same counts. |
| Weighted population (sum of `PERWT`) | 333,053,243, ours 333,053,243 | 334,530,273, ours 334,530,273 | Codebook, Total line of the `SEX` table (weighted by `PERWT22F`, `PERWT23F`) |
| Mean total expenditure per person (weighted) | $6,765, ours $6,764.68 | Not found, see below | 2022: Statistical Brief #560, Figure 2 "Overall" (average expenditure per person, 2022) |
| Persons by `TOTEXP` band, unweighted and weighted | All 5 bands equal | All 5 bands equal | Codebook, `TOTEXP22` and `TOTEXP23` tables |

Persons equal exactly. The weighted population equals the codebook total to the whole person. The
2022 weighted mean is $6,764.68 and AHRQ publishes $6,765 to the dollar.

## The 2023 weighted mean

No AHRQ publication with a 2023 mean total expenditure per person was found.

- Statistical Brief #560 (March 2025) covers 2018 to 2022 and gives the 2022 mean. Later briefs on
  expenditures cover conditions, not the overall mean.
- The HC-251 documentation page and codebook do not state a mean.
- AHRQ's MEPS-HC dashboard (`https://datatools.ahrq.gov/meps-hc`, Use, Expenditures and Population)
  has the figure behind an interactive tool with an Excel download, which cannot be scripted. Our
  value would be $7,487.26 (weighted mean of `TOTEXP23`), but a remembered or computed number is
  not a published figure, so it is not used as a check.

To cover 2023 as well, the codebook's `TOTEXP23` table is used. It prints the unweighted and
weighted persons in five expenditure bands (zero, then four quartile bands). All five bands match in
both years, so the whole weighted expenditure distribution for 2023 is checked, only the dollar mean
is not.

If the user downloads the dashboard's 2023 mean total expenditure per person, adding it to
`tests/data/published_figures.csv` as `mean_totexp_per_person` for 2023 switches the check on
(and removing the one test in `tests/test_reconciliation.py` that records its absence).
