"""Diagnostics for the final structure on the train and 2022 test splits (issue #33).

The final structure is candidate (a) with the 10 rating factors chosen at decision gate 7, part 2.
The tables are aggregates. Uncertainty bands come from resampling households, because members of
a household are not independent. Nothing here tunes the model. The tables show how it behaves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from health_pricing.models import factors, large_claims, metrics
from health_pricing.models.frame import FACTORS, Frames

AE_LOW, AE_HIGH = 0.85, 1.15
MIN_CLAIMANTS = 30
SEED = 20221102


def final_result(prepared: Frames) -> factors.OptionResult:
    """The final structure: candidate (a) on the final rating factors, rebalanced on train."""
    return factors.scored_option(
        prepared, "final", factors.FINAL_RATING, factors.controls_for("final")
    )


def reference_result(prepared: Frames) -> factors.OptionResult:
    """The all-factor model, which the final structure is compared with."""
    return factors.scored_option(prepared, "all_factors", factors.FACTORS, [])


def factor_role(factor: str) -> str:
    """Whether a factor is a rating factor, analysis-only, or dropped by the selection rule."""
    if factor in factors.FINAL_RATING:
        return "rating"
    if factor in factors.controls_for("final"):
        return "analysis_only"
    return "dropped"


def ae_by_level(prepared: Frames, result: factors.OptionResult) -> pd.DataFrame:
    """A/E for every level of every factor on train and test, with the 30-claimant rule applied.

    `outside_band` is set for levels with at least 30 claimants whose A/E is outside 0.85 to
    1.15. The role says how the factor enters the structure, because an analysis-only factor is
    priced at its reference level and is expected to show an A/E that follows its true effect.
    """
    rows = []
    for split, frame in (("train", prepared.train), ("test", prepared.test)):
        table = metrics.ae_by_factor(frame, result.candidate.prediction(split), FACTORS)
        table.insert(0, "split", split)
        rows.append(table)
    out = pd.concat(rows, ignore_index=True)
    out.insert(2, "role", out["factor"].map(factor_role))
    out["enough_claimants"] = out["claimants"] >= MIN_CLAIMANTS
    out["outside_band"] = out["enough_claimants"] & ((out["a_e"] < AE_LOW) | (out["a_e"] > AE_HIGH))
    return out


def flagged_levels(table: pd.DataFrame) -> pd.DataFrame:
    """The levels outside the band with enough claimants, rating factors first."""
    flagged = table[table["outside_band"]].copy()
    order = {"rating": 0, "analysis_only": 1, "dropped": 2}
    flagged["order"] = flagged["role"].map(order)
    return (
        flagged.sort_values(["split", "order", "factor", "level"])
        .drop(columns="order")
        .reset_index(drop=True)
    )


def flag_summary(table: pd.DataFrame) -> pd.DataFrame:
    """For each split and role, the levels checked and the number outside the band."""
    checked = table[table["enough_claimants"]]
    summary = checked.groupby(["split", "role"]).agg(
        levels_checked=("a_e", "size"), levels_outside_band=("outside_band", "sum")
    )
    return summary.reset_index()


def residual_summary(frame: pd.DataFrame, predicted, n: int = 10) -> pd.DataFrame:
    """Tweedie (p = 1.5) deviance residuals by group of predicted cost per exposure year.

    A residual is the signed square root of a person-year's deviance. A person-year with no cost
    always has a negative residual of -2 times the prediction to the power 0.25, so it says
    nothing about fit. The table therefore gives the mean deviance of every person-year, and the
    residual summaries for claimants only (the mean shows bias, the standard deviation spread, and
    the last column is the share beyond 2 in either direction).
    """
    predicted = np.asarray(predicted, dtype=float)
    cost = frame["cost"].to_numpy(dtype=float)
    unit = metrics.tweedie_unit_deviance(cost, predicted)
    residual = np.sign(cost - predicted) * np.sqrt(unit)
    group = metrics._buckets(
        pd.Series(predicted / frame["exposure"].to_numpy(), index=frame.index),
        frame["exposure"],
        n,
    )
    work = pd.DataFrame(
        {"group": group.to_numpy(), "unit": unit, "residual": residual, "claimant": cost > 0}
    )
    table = work.groupby("group").agg(person_years=("unit", "size"), mean_deviance=("unit", "mean"))
    claimants = work[work["claimant"]].groupby("group")["residual"]
    table["claimants"] = claimants.size()
    table["mean_residual_claimants"] = claimants.mean()
    table["sd_residual_claimants"] = claimants.std()
    table["share_claimants_beyond_2"] = claimants.apply(lambda r: float((r.abs() > 2).mean()))
    return table.reset_index()


def lift_with_bands(
    frame: pd.DataFrame, predicted, n: int = 10, n_boot: int = 1000, seed: int = SEED
) -> pd.DataFrame:
    """A/E by group of predicted cost per exposure year, with a 95 percent household band.

    The groups are fixed from the full sample. Households are then resampled with replacement and
    A/E is recomputed in each group, so the band shows how much each group's A/E could move.
    """
    predicted = np.asarray(predicted, dtype=float)
    actual = frame["cost"].to_numpy(dtype=float)
    group = (
        metrics._buckets(
            pd.Series(predicted / frame["exposure"].to_numpy(), index=frame.index),
            frame["exposure"],
            n,
        ).to_numpy()
        - 1
    )
    households = pd.factorize(frame["DUID"])[0]
    count = households.max() + 1
    cell = households * n + group
    actual_cells = np.bincount(cell, weights=actual, minlength=count * n).reshape(count, n)
    predicted_cells = np.bincount(cell, weights=predicted, minlength=count * n).reshape(count, n)
    draws = np.random.default_rng(seed).multinomial(count, np.full(count, 1 / count), n_boot)
    ratio = (draws @ actual_cells) / (draws @ predicted_cells)
    table = pd.DataFrame(
        {
            "group": np.arange(1, n + 1),
            "person_years": np.bincount(group, minlength=n),
            "actual": actual_cells.sum(axis=0),
            "predicted": predicted_cells.sum(axis=0),
        }
    )
    table["a_e"] = table["actual"] / table["predicted"]
    table["lower_95"] = np.quantile(ratio, 0.025, axis=0)
    table["upper_95"] = np.quantile(ratio, 0.975, axis=0)
    return table


def lift_by_split(
    prepared: Frames,
    results: dict[str, factors.OptionResult],
    n_groups: tuple[int, ...] = (10, 5),
) -> pd.DataFrame:
    """Lift tables with bands for each split, model and number of groups, for saving."""
    rows = []
    for split, frame in (("train", prepared.train), ("test", prepared.test)):
        for name, result in results.items():
            for n in n_groups:
                table = lift_with_bands(frame, result.candidate.prediction(split), n)
                table.insert(0, "groups", n)
                table.insert(0, "model", name)
                table.insert(0, "split", split)
                rows.append(table)
    return pd.concat(rows, ignore_index=True)


def end_groups(lift: pd.DataFrame) -> pd.DataFrame:
    """The lowest and highest group A/E for each split, model and number of groups.

    `top_predicted_over_actual` is how far the highest group's prediction is above its actual cost
    (the reciprocal of A/E, minus 1). A smaller gap means less over-spreading at the top.
    """
    rows = []
    for (split, model, groups), table in lift.groupby(["split", "model", "groups"], sort=False):
        low, high = table.iloc[0], table.iloc[-1]
        rows.append(
            {
                "split": split,
                "model": model,
                "groups": groups,
                "lowest_group_a_e": low["a_e"],
                "highest_group_a_e": high["a_e"],
                "top_predicted_over_actual": 1 / high["a_e"] - 1,
            }
        )
    return pd.DataFrame(rows)


def overall_check(
    prepared: Frames, result: factors.OptionResult, n_boot: int = 2000, seed: int = SEED
) -> pd.DataFrame:
    """Overall A/E on train and test, with the tolerance of 2 and 5 percent and a household band.

    `a_e_if_load_matched` restates A/E as if the large-claim load had matched the split's own
    excess over the cap. It is information only, and the load is not tuned to it.
    """
    rows = []
    for split, frame, tolerance in (
        ("train", prepared.train, 0.02),
        ("test", prepared.test, 0.05),
    ):
        predicted = np.asarray(result.candidate.prediction(split), dtype=float)
        a_e = float(frame["cost"].sum() / predicted.sum())
        households = pd.factorize(frame["DUID"])[0]
        count = households.max() + 1
        actual_h = np.bincount(households, weights=frame["cost"].to_numpy(), minlength=count)
        predicted_h = np.bincount(households, weights=predicted, minlength=count)
        draws = np.random.default_rng(seed).multinomial(count, np.full(count, 1 / count), n_boot)
        ratio = (draws @ actual_h) / (draws @ predicted_h)
        excess = (frame["cost"] - large_claims.capped_cost(frame["cost"])).sum()
        own_load = excess / large_claims.capped_cost(frame["cost"]).sum()
        rows.append(
            {
                "split": split,
                "a_e": a_e,
                "tolerance": tolerance,
                "within_tolerance": abs(a_e - 1) <= tolerance,
                "lower_95": float(np.quantile(ratio, 0.025)),
                "upper_95": float(np.quantile(ratio, 0.975)),
                "own_excess_load": float(own_load),
                "a_e_if_load_matched": a_e * (1 + large_claims.PROVISIONAL_LOAD) / (1 + own_load),
            }
        )
    return pd.DataFrame(rows)
