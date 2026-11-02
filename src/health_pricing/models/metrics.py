"""Metrics shared by every M3 candidate (issue #23).

A prediction is the expected annual cost of a person-year, exposure included. Actual is the
observed annual cost of the same person-year. Rows with equal predicted risk (prediction per
exposure year) are tied, so the order of rows never changes a result.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TWEEDIE_POWER = 1.5
POWER_CHECKS = (1.3, 1.5, 1.7)


def tweedie_deviance(actual, predicted, power: float = TWEEDIE_POWER) -> float:
    """Total Tweedie deviance for 1 < power < 2. Actuals may be zero, predictions must not."""
    if not 1 < power < 2:
        raise ValueError("power must be between 1 and 2")
    y = np.asarray(actual, dtype=float)
    mu = np.asarray(predicted, dtype=float)
    if (mu <= 0).any():
        raise ValueError("predictions must be positive")
    unit = 2 * (
        y ** (2 - power) / ((1 - power) * (2 - power))
        - y * mu ** (1 - power) / (1 - power)
        + mu ** (2 - power) / (2 - power)
    )
    return float(unit.sum())


def deviance_by_power(actual, predicted, powers=POWER_CHECKS) -> dict[float, float]:
    """The deviance at each power, to re-check a ranking of candidates."""
    return {p: tweedie_deviance(actual, predicted, p) for p in powers}


def _grouped(actual, predicted, exposure) -> pd.DataFrame:
    """One row per distinct predicted risk, ordered from lowest to highest."""
    frame = pd.DataFrame(
        {
            "actual": np.asarray(actual, dtype=float),
            "predicted": np.asarray(predicted, dtype=float),
            "exposure": np.asarray(exposure, dtype=float),
        }
    )
    frame["risk"] = frame["predicted"] / frame["exposure"]
    return frame.groupby("risk", as_index=False)[["actual", "predicted", "exposure"]].sum()


def gini(actual, predicted, exposure) -> float:
    """Exposure-weighted Gini of the ranking by predicted risk.

    The Lorenz curve plots the cumulative share of actual cost against the cumulative share of
    exposure, with person-years ordered from lowest to highest predicted risk. Gini is 1 minus
    twice the area under it. A constant prediction gives 0.
    """
    grouped = _grouped(actual, predicted, exposure)
    total_actual = grouped["actual"].sum()
    if total_actual == 0:
        return 0.0
    x = np.concatenate([[0.0], grouped["exposure"].cumsum() / grouped["exposure"].sum()])
    y = np.concatenate([[0.0], grouped["actual"].cumsum() / total_actual])
    area = float(((y[1:] + y[:-1]) / 2 * np.diff(x)).sum())
    return 1 - 2 * area


def _buckets(order_key: pd.Series, exposure: pd.Series, n: int) -> pd.Series:
    """Exposure-weighted groups 1 to n by the order of `order_key`, ties kept stable."""
    order = order_key.sort_values(kind="stable").index
    cumulative = exposure.loc[order].cumsum()
    midpoint = (cumulative - exposure.loc[order] / 2) / exposure.sum()
    bucket = np.minimum((midpoint * n).astype(int), n - 1) + 1
    return bucket.reindex(order_key.index)


def lift_table(actual, predicted, exposure, n: int = 10) -> pd.DataFrame:
    """Actual and expected cost by predicted-risk group. Also the A/E by predicted-cost decile."""
    frame = pd.DataFrame(
        {
            "actual": np.asarray(actual, dtype=float),
            "predicted": np.asarray(predicted, dtype=float),
            "exposure": np.asarray(exposure, dtype=float),
        }
    )
    frame["group"] = _buckets(frame["predicted"] / frame["exposure"], frame["exposure"], n)
    table = frame.groupby("group").agg(
        person_years=("actual", "size"),
        exposure=("exposure", "sum"),
        actual=("actual", "sum"),
        predicted=("predicted", "sum"),
    )
    table["actual_per_exposure"] = table["actual"] / table["exposure"]
    table["predicted_per_exposure"] = table["predicted"] / table["exposure"]
    table["a_e"] = table["actual"] / table["predicted"]
    table["lift"] = table["actual_per_exposure"] / (frame["actual"].sum() / frame["exposure"].sum())
    return table.reset_index()


ae_by_predicted_decile = lift_table


def double_lift_table(actual, predicted_a, predicted_b, exposure, n: int = 10) -> pd.DataFrame:
    """Actual against two sets of predictions, grouped by the ratio of A to B.

    Groups run from where A predicts lowest relative to B to where it predicts highest. The
    model whose predictions track actual cost better has an actual-to-predicted ratio nearer 1
    in every group.
    """
    frame = pd.DataFrame(
        {
            "actual": np.asarray(actual, dtype=float),
            "predicted_a": np.asarray(predicted_a, dtype=float),
            "predicted_b": np.asarray(predicted_b, dtype=float),
            "exposure": np.asarray(exposure, dtype=float),
        }
    )
    frame["group"] = _buckets(frame["predicted_a"] / frame["predicted_b"], frame["exposure"], n)
    table = frame.groupby("group")[["exposure", "actual", "predicted_a", "predicted_b"]].sum()
    table["a_e_a"] = table["actual"] / table["predicted_a"]
    table["a_e_b"] = table["actual"] / table["predicted_b"]
    return table.reset_index()


def ae_by_factor(frame: pd.DataFrame, predicted, factors: list[str]) -> pd.DataFrame:
    """Actual, expected and A/E for each level of each factor, with claimants for the 30 rule."""
    data = frame[[*factors, "exposure", "cost", "claimant"]].copy()
    data["predicted"] = np.asarray(predicted, dtype=float)
    rows = []
    for factor in factors:
        grouped = data.groupby(data[factor].astype("object").fillna("missing"), observed=True)
        table = grouped.agg(
            person_years=("cost", "size"),
            exposure=("exposure", "sum"),
            claimants=("claimant", "sum"),
            actual=("cost", "sum"),
            expected=("predicted", "sum"),
        ).reset_index(names="level")
        table.insert(0, "factor", factor)
        rows.append(table)
    result = pd.concat(rows, ignore_index=True)
    result["a_e"] = result["actual"] / result["expected"]
    return result


def baseline_predictions(train: pd.DataFrame, frame: pd.DataFrame) -> np.ndarray:
    """The overall mean cost per exposure year in train, times each person-year's exposure."""
    rate = train["cost"].sum() / train["exposure"].sum()
    return (rate * frame["exposure"]).to_numpy()


def score(frame: pd.DataFrame, predicted, power: float = TWEEDIE_POWER) -> dict[str, float]:
    """The headline scores every candidate is compared on."""
    return {
        "tweedie_deviance": tweedie_deviance(frame["cost"], predicted, power),
        "mean_tweedie_deviance": tweedie_deviance(frame["cost"], predicted, power) / len(frame),
        "gini": gini(frame["cost"], predicted, frame["exposure"]),
        "a_e": float(frame["cost"].sum() / np.sum(predicted)),
    }


def baseline_scores(train: pd.DataFrame, test: pd.DataFrame, power: float = TWEEDIE_POWER):
    """Scores of the overall-mean baseline on train and test."""
    rows = []
    for name, frame in (("train", train), ("test", test)):
        rows.append({"split": name, **score(frame, baseline_predictions(train, frame), power)})
    return pd.DataFrame(rows)
