"""Forward accuracy of the frozen model on 2023 (M5, issue #44).

The technical model and the tariff are scored on the 2023 rows with the forecast trend decided at
gate 4, part 2 (expected annual cost multiplied by the factor). The yardstick is the one of the GLM
notebook. Intervals come from resampling households with a fixed seed. Every table is an aggregate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from health_pricing.models import diagnostics, glm, metrics, trend
from health_pricing.models.frame import FACTORS
from health_pricing.models.outofsample import TARIFF, TECHNICAL, FrozenModel, OutOfTime

SEED = trend.SEED
N_BOOT = trend.N_BOOT
AE_LOW, AE_HIGH = diagnostics.AE_LOW, diagnostics.AE_HIGH
MIN_CLAIMANTS = diagnostics.MIN_CLAIMANTS
BASELINE = "Baseline (2022 train mean)"


def forecast(
    frozen: FrozenModel, oot: OutOfTime, factor: float, mode: str = trend.COST
) -> dict[str, np.ndarray]:
    """Both models' predicted annual cost on 2023, with the forecast trend."""
    pieces = trend.out_of_time_parts(frozen, oot)
    predicted = trend.forecast_prediction(frozen, oot, pieces, factor, mode)
    return {TECHNICAL: predicted["technical"], TARIFF: predicted["tariff"]}


def grouped_ae(
    households: np.ndarray,
    labels: pd.Series,
    actual: np.ndarray,
    predicted: np.ndarray,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> pd.DataFrame:
    """A/E for each label with a 95 percent household interval, and against the overall A/E.

    `relative_a_e` is the A/E of the group over the overall A/E, so it shows a difference in the
    structure apart from a difference in level. Its interval comes from the same resamples, with
    the overall A/E of each resample, so a group that moves with the whole book is near 1.
    """
    codes, names = pd.factorize(labels.astype(str), sort=True)
    count = households.max() + 1
    groups = len(names)
    cell = households * groups + codes
    actual_cells = np.bincount(cell, weights=actual, minlength=count * groups).reshape(
        count, groups
    )
    predicted_cells = np.bincount(cell, weights=predicted, minlength=count * groups).reshape(
        count, groups
    )
    draws = np.random.default_rng(seed).multinomial(count, np.full(count, 1 / count), n_boot)
    boot_actual, boot_predicted = draws @ actual_cells, draws @ predicted_cells
    ratio = boot_actual / boot_predicted
    overall = boot_actual.sum(axis=1) / boot_predicted.sum(axis=1)
    point = actual_cells.sum(axis=0) / predicted_cells.sum(axis=0)
    point_overall = actual.sum() / predicted.sum()
    relative = ratio / overall[:, None]
    return pd.DataFrame(
        {
            "label": names,
            "actual": actual_cells.sum(axis=0),
            "expected": predicted_cells.sum(axis=0),
            "a_e": point,
            "lower_95": np.quantile(ratio, 0.025, axis=0),
            "upper_95": np.quantile(ratio, 0.975, axis=0),
            "relative_a_e": point / point_overall,
            "relative_lower_95": np.quantile(relative, 0.025, axis=0),
            "relative_upper_95": np.quantile(relative, 0.975, axis=0),
        }
    )


def overall(
    oot: OutOfTime, predictions: dict[str, np.ndarray], n_boot: int = N_BOOT, seed: int = SEED
) -> pd.DataFrame:
    """Overall A/E of each model on 2023 with a household interval."""
    frame = oot.frame
    households = pd.factorize(frame["DUID"])[0]
    rows = []
    for name, predicted in predictions.items():
        table = grouped_ae(
            households,
            pd.Series("all", index=frame.index),
            frame["cost"].to_numpy(),
            predicted,
            n_boot,
            seed,
        )
        rows.append({"model": name, **table.iloc[0].drop("label")})
    return pd.DataFrame(rows)


def by_level(
    oot: OutOfTime, predicted: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED
) -> pd.DataFrame:
    """A/E for every level of every factor on 2023, with household bands and the 30-claimant rule.

    `outside_band` is set for levels with at least 30 claimants whose A/E is outside 0.85 to 1.15.
    `moves_with_the_book` is set when the interval of the relative A/E contains 1, which means the
    level differs from the overall A/E by no more than sampling noise.
    """
    frame = oot.frame
    households = pd.factorize(frame["DUID"])[0]
    claimants = (frame["capped_cost"] > 0).astype(int)
    rows = []
    for factor in FACTORS:
        labels = frame[factor].astype(object)
        table = grouped_ae(households, labels, frame["cost"].to_numpy(), predicted, n_boot, seed)
        stats = (
            pd.DataFrame(
                {"label": labels.astype(str), "claimants": claimants, "exposure": frame["exposure"]}
            )
            .groupby("label")
            .agg(
                person_years=("claimants", "size"),
                claimants=("claimants", "sum"),
                exposure=("exposure", "sum"),
            )
        )
        table = table.merge(stats, left_on="label", right_index=True)
        table.insert(0, "factor", factor)
        table.insert(1, "role", diagnostics.factor_role(factor))
        rows.append(table.rename(columns={"label": "level"}))
    out = pd.concat(rows, ignore_index=True)
    out["enough_claimants"] = out["claimants"] >= MIN_CLAIMANTS
    out["outside_band"] = out["enough_claimants"] & ((out["a_e"] < AE_LOW) | (out["a_e"] > AE_HIGH))
    out["moves_with_the_book"] = (out["relative_lower_95"] <= 1) & (out["relative_upper_95"] >= 1)
    return out


def flagged(table: pd.DataFrame) -> pd.DataFrame:
    """The levels outside the band with enough claimants, rating factors first."""
    out = table[table["outside_band"]].copy()
    order = {"rating": 0, "analysis_only": 1, "dropped": 2}
    out["order"] = out["role"].map(order)
    return (
        out.sort_values(["order", "factor", "level"]).drop(columns="order").reset_index(drop=True)
    )


def by_age_group(
    oot: OutOfTime, predictions: dict[str, np.ndarray], n_boot: int = N_BOOT, seed: int = SEED
) -> pd.DataFrame:
    """A/E of each model by children and the three adult age groups."""
    frame = oot.spline_frame
    households = pd.factorize(frame["DUID"])[0]
    labels = trend.age_group(frame)
    rows = []
    for name, predicted in predictions.items():
        table = grouped_ae(households, labels, frame["cost"].to_numpy(), predicted, n_boot, seed)
        table.insert(0, "model", name)
        rows.append(table.rename(columns={"label": "age_group"}))
    out = pd.concat(rows, ignore_index=True)
    order = {g: i for i, g in enumerate(trend.AGE_GROUPS)}
    return out.sort_values(
        ["model", "age_group"], key=lambda c: c.map(order) if c.name == "age_group" else c
    )


def lift(
    oot: OutOfTime,
    predictions: dict[str, np.ndarray],
    n_groups: tuple[int, ...] = (10, 5),
    n_boot: int = N_BOOT,
) -> pd.DataFrame:
    """Lift tables with household bands for each model and number of groups, on 2023."""
    rows = []
    for name, predicted in predictions.items():
        for n in n_groups:
            table = diagnostics.lift_with_bands(oot.frame, predicted, n, n_boot)
            table.insert(0, "groups", n)
            table.insert(0, "model", name)
            rows.append(table)
    return pd.concat(rows, ignore_index=True)


def scores(frozen: FrozenModel, oot: OutOfTime, predictions: dict[str, np.ndarray]) -> pd.DataFrame:
    """Tweedie deviance at three powers, Gini and A/E on 2023, with the 2022 baseline for reference.

    The baseline predicts the 2022 train cost per exposure year for every person-year, so its Gini
    is 0.
    `deviance_reduction_pct` is against that baseline.
    """
    frame = oot.frame
    baseline = metrics.baseline_predictions(frozen.prepared.train, frame)
    table = pd.concat(
        [
            glm.candidate_scores(name, 0, {"2023": (frame, predicted)})
            for name, predicted in {BASELINE: baseline, **predictions}.items()
        ],
        ignore_index=True,
    )
    reference = table.loc[table["candidate"] == BASELINE, "tweedie_deviance"].iloc[0]
    table["deviance_reduction_pct"] = 100 * (1 - table["tweedie_deviance"] / reference)
    return table.drop(columns=["split", "parameters", "dropped_reason"])


def double_lift(oot: OutOfTime, predictions: dict[str, np.ndarray], n: int = 10) -> pd.DataFrame:
    """Double lift of the tariff against the technical model on 2023."""
    frame = oot.frame
    table = metrics.double_lift_table(
        frame["cost"], predictions[TARIFF], predictions[TECHNICAL], frame["exposure"], n
    )
    return table.rename(
        columns={
            "predicted_a": f"predicted {TARIFF}",
            "predicted_b": f"predicted {TECHNICAL}",
            "a_e_a": f"A/E {TARIFF}",
            "a_e_b": f"A/E {TECHNICAL}",
        }
    )
