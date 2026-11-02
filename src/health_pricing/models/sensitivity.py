"""Sensitivity of the 2023 results to the forecast trend (M5, issue #48).

The low, central and high trends are the lower quartile, the median and the upper quartile of the
CMS Unified Rate Review utilization trend decided at gate 4, part 2. Each is a multiplier on
expected annual cost. The trend is a level factor, so it cannot change the relativities, only the
A/E and the size of a rebase.
"""

from __future__ import annotations

import dataclasses

import pandas as pd

from health_pricing.models import monitoring, recalibration
from health_pricing.models.outofsample import FrozenModel, OutOfTime

LOW, CENTRAL, HIGH = "Low", "Central", "High"
SOURCE = "CMS URR PUF plan year 2023, Worksheet I, Year 2 utilization, blend"


def scenario_factors(external_row) -> dict[str, float]:
    """The low (lower quartile), central (median) and high (upper quartile) trend multipliers."""
    return {
        LOW: float(external_row["p25"]),
        CENTRAL: float(external_row["p50"]),
        HIGH: float(external_row["p75"]),
    }


def _leading(table: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return table[[*columns, *[c for c in table if c not in columns]]]


def trend_sensitivity(
    frozen: FrozenModel,
    oot: OutOfTime,
    factors: dict[str, float],
    n_boot: int = monitoring.N_BOOT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Overall A/E and A/E by broad age group for each trend, for both models, with intervals."""
    overall, ages = [], []
    for name, factor in factors.items():
        predictions = monitoring.forecast(frozen, oot, factor)
        overall.append(
            monitoring.overall(oot, predictions, n_boot).assign(scenario=name, trend=factor)
        )
        ages.append(
            monitoring.by_age_group(oot, predictions, n_boot).assign(scenario=name, trend=factor)
        )
    columns = ["scenario", "trend"]
    return (
        _leading(pd.concat(overall, ignore_index=True), columns),
        _leading(pd.concat(ages, ignore_index=True), columns),
    )


def relativity_effect(
    frozen: FrozenModel, oot: OutOfTime, factors: dict[str, float]
) -> pd.DataFrame:
    """How much the trend changes the ratios between rows, which is none for a level factor.

    For each model, the prediction under each trend is divided by the central one. The spread of
    that ratio over the rows is the effect on the relativities.
    """
    central = monitoring.forecast(frozen, oot, factors[CENTRAL])
    rows = []
    for name, factor in factors.items():
        for model, predicted in monitoring.forecast(frozen, oot, factor).items():
            ratio = predicted / central[model]
            rows.append(
                {
                    "scenario": name,
                    "model": model,
                    "ratio_to_central": float(ratio.mean()),
                    "spread_of_ratio_over_rows": float(ratio.max() - ratio.min()),
                }
            )
    return pd.DataFrame(rows)


def conclusions(
    evidence: recalibration.Evidence, overall: pd.DataFrame, model: str
) -> pd.DataFrame:
    """The recalibration rule under each trend, with the total move against the 2022 level.

    The structure, mix and ranking evidence do not depend on the trend. Only the A/E and its
    interval do. The total move is the trend times the rebase factor, which is the level of 2023
    cost against the 2022 train level, at the sampling and at the persistence weight.
    """
    rows = []
    for _, row in overall[overall["model"] == model].iterrows():
        changed = dataclasses.replace(
            evidence, a_e=row["a_e"], a_e_lower=row["lower_95"], a_e_upper=row["upper_95"]
        )
        result = recalibration.recommend(changed)
        rows.append(
            {
                "scenario": row["scenario"],
                "trend": row["trend"],
                "a_e": row["a_e"],
                "action": result.action,
                "rebase_factor_sampling_weight": result.base_rate_factor,
                "rebase_factor_persistence_weight": result.lower_base_rate_factor,
                "total_move_sampling_weight": row["trend"] * result.base_rate_factor,
                "total_move_persistence_weight": row["trend"] * result.lower_base_rate_factor,
            }
        )
    return pd.DataFrame(rows)


def same_action(table: pd.DataFrame) -> bool:
    """Whether every scenario gives the same action."""
    return bool(table["action"].nunique() == 1)
