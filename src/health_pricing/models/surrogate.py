"""Surrogate model (tariff) of a fitted candidate (issue #32).

A surrogate model (tariff) is a multiplicative log-link GLM fitted to a candidate's predicted
annual cost, and not to actual claims. Pricing actuaries call this tariff extraction, or fitting
a rating structure to the technical premium. Its prediction is a base rate times one relativity
per factor level, times exposure, so it is what a rating engine can hold. The response is the
candidate's prediction on the train split. The same rating factors are used, with the `unknown`
control priced at the reference as in rating. The surrogate model (tariff) is scored on the test
split with the same yardstick as the candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.genmod.families import links

from health_pricing.models import comparison, glm
from health_pricing.models.frame import FACTORS, Frames


@dataclass
class SurrogateTariff:
    factors: list[str]
    columns: list[str]
    result: object

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        """Base rate times the relativities of the person-year's levels, times its exposure."""
        matrix = glm.design_matrix(frame, self.factors, rating=True)
        matrix = matrix.reindex(columns=self.columns, fill_value=0.0)
        return np.asarray(self.result.predict(matrix, offset=np.log(frame["exposure"].to_numpy())))

    @property
    def parameters(self) -> int:
        return len(self.result.params)

    def relativities(self) -> pd.DataFrame:
        """The base rate (the constant) and the relativity of each factor level."""
        params = self.result.params
        return pd.DataFrame(
            {"term": params.index, "coefficient": params.to_numpy(), "relativity": np.exp(params)}
        )


def fit_surrogate_tariff(
    train: pd.DataFrame, predicted, factors: list[str] = FACTORS
) -> SurrogateTariff:
    """Fit the surrogate model (tariff) to `predicted`, the candidate's cost on the train frame.

    The model is a log-link GLM with an offset of log exposure. It is fitted to predictions with
    equal weight, and its estimating equations keep the total predicted cost of the train frame
    equal to the candidate's.
    """
    matrix = glm.design_matrix(train, factors, rating=True)
    columns = [c for c in matrix if c == "const" or matrix[c].any()]
    glm._check_rank(matrix[columns])
    result = sm.GLM(
        np.asarray(predicted, dtype=float),
        matrix[columns],
        family=sm.families.Poisson(link=links.Log()),
        offset=np.log(train["exposure"].to_numpy()),
    ).fit()
    return SurrogateTariff(list(factors), columns, result)


def surrogate_candidate(
    prepared: Frames,
    reference: comparison.Candidate,
    name: str = "a_surrogate",
    factors: list[str] = FACTORS,
) -> tuple[SurrogateTariff, comparison.Candidate]:
    """The surrogate model (tariff) of a candidate, as a candidate that can be scored."""
    tariff = fit_surrogate_tariff(prepared.train, reference.train, factors)
    unit = {s: getattr(prepared, s).assign(exposure=1.0) for s in ("train", "test")}
    candidate = comparison.Candidate(
        name,
        tariff.parameters,
        tariff.predict(prepared.train),
        tariff.predict(prepared.test),
        tariff.predict(unit["train"]),
        tariff.predict(unit["test"]),
    )
    return tariff, candidate


def departure_from_reference(
    reference: comparison.Candidate, surrogate: comparison.Candidate
) -> pd.DataFrame:
    """How far the surrogate model (tariff) is from the candidate it stands in for.

    The departure of a row is the surrogate's prediction over the candidate's, minus 1. The table
    gives the typical (median and root mean square of the log ratio), the 99th percentile and the
    largest absolute departure, and the ratio of total predicted cost, on each split.
    """
    rows = []
    for split in ("train", "test"):
        ratio = surrogate.prediction(split) / reference.prediction(split)
        departure = np.abs(ratio - 1)
        rows.append(
            {
                "split": split,
                "median_abs_departure": float(np.median(departure)),
                "rms_log_departure": float(np.sqrt(np.mean(np.log(ratio) ** 2))),
                "p99_abs_departure": float(np.quantile(departure, 0.99)),
                "max_abs_departure": float(departure.max()),
                "total_cost_ratio": float(
                    surrogate.prediction(split).sum() / reference.prediction(split).sum()
                ),
            }
        )
    return pd.DataFrame(rows)
