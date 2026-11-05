"""The in-force book, scenario impact and dislocation (M6, issue #61).

The in-force book is exposure by rating cell (age band, region and the seven condition flags),
built from the 2022 modelling table. It holds exposure only, so no person-level record is kept.
A cell with fewer than `MIN_PERSONS` person-years rows is merged into the nearest larger cell of
the same age band and region (fewest condition flags that differ, then the larger exposure), so
total exposure is unchanged. `apply_scenario` applies a rate change to the book and reports the
impact and the dislocation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from health_pricing.models import outofsample
from health_pricing.rating import engine

MIN_PERSONS = 10
CONDITIONS = ["HIBPDX", "CHDDX", "OHRTDX", "CHOLDX", "CANCERDX", "ARTHDX", "ASTHDX"]
KEYS = ["age", "region", *CONDITIONS]
AGE_GROUPS = ["Children", "18-39", "40-64", "65+"]
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)


def age_group(band) -> pd.Series:
    """The age group of each band label."""
    low = pd.Series(band).astype(str).str.extract(r"(\d+)")[0].astype(int)
    return pd.cut(low, [-1, 17, 39, 64, 200], labels=AGE_GROUPS).astype(str)


def build_book(frame: pd.DataFrame | None = None, min_persons: int = MIN_PERSONS) -> pd.DataFrame:
    """Exposure by rating cell from the modelling table, with small cells merged."""
    if frame is None:
        frozen = outofsample.freeze()
        frame = pd.concat([frozen.prepared.train, frozen.prepared.test])
    data = frame[[*KEYS, "exposure"]].copy()
    for key in KEYS:
        data[key] = data[key].astype(str)
    grouped = data.groupby(KEYS, observed=True)["exposure"].agg(["sum", "size"]).reset_index()
    grouped = grouped.rename(columns={"sum": "exposure", "size": "persons"})
    large = grouped[grouped["persons"] >= min_persons].copy()
    small = grouped[grouped["persons"] < min_persons]
    for _, cell in small.iterrows():
        pool = large[(large["age"] == cell["age"]) & (large["region"] == cell["region"])]
        if pool.empty:
            pool = large[large["age"] == cell["age"]]
        differ = (pool[CONDITIONS].to_numpy() != cell[CONDITIONS].to_numpy()).sum(axis=1)
        order = pd.DataFrame({"differ": differ, "exposure": -pool["exposure"].to_numpy()})
        target = order.sort_values(["differ", "exposure"], kind="stable").index[0]
        large.loc[pool.index[target], "exposure"] += cell["exposure"]
    book = large.drop(columns="persons").reset_index(drop=True)
    return book


def cell_premiums(book: pd.DataFrame, tariff: engine.Tariff) -> pd.Series:
    """The engine premium of each cell for one exposure-year, in dollars."""
    table = tariff.relativities.set_index(["factor", "level"])["relativity"]
    premium = pd.Series(tariff.base_rate_2022 * tariff.trend * tariff.rebase, index=book.index)
    for factor in tariff.factors:
        keys = pd.MultiIndex.from_arrays([[factor] * len(book), book[factor].astype(str)])
        premium = premium * table.reindex(keys).to_numpy()
    return premium


@dataclass
class Scenario:
    """A rate change. Changes are fractions, so 0.05 is +5 percent.

    `relativity_changes` maps (factor, level) to a change in that relativity. `cap` is the
    largest premium increase allowed for a cell and `floor` the largest decrease (a negative
    number). Caps and floors apply after the base and relativity changes.
    """

    base_change: float = 0.0
    relativity_changes: dict[tuple[str, str], float] = field(default_factory=dict)
    cap: float | None = None
    floor: float | None = None


def apply_scenario(book: pd.DataFrame, scenario: Scenario, tariff: engine.Tariff) -> dict:
    """Old and new premium by cell, with totals and the cost of the cap and floor."""
    cells = book.copy()
    cells["old_premium"] = cell_premiums(book, tariff)
    multiplier = pd.Series(1.0 + scenario.base_change, index=book.index)
    for (factor, level), change in scenario.relativity_changes.items():
        multiplier = multiplier * np.where(book[factor].astype(str) == str(level), 1 + change, 1.0)
    uncapped = multiplier.to_numpy()
    change = uncapped - 1.0
    if scenario.cap is not None:
        change = np.minimum(change, scenario.cap)
    if scenario.floor is not None:
        change = np.maximum(change, scenario.floor)
    cells["uncapped_change_pct"] = 100 * (uncapped - 1.0)
    cells["change_pct"] = 100 * change
    cells["new_premium"] = cells["old_premium"] * (1 + change)
    cells["change_amount"] = cells["new_premium"] - cells["old_premium"]
    scale = (tariff.scaling or {}).get("gbp_per_usd_premium")
    if scale:
        cells["old_premium_gbp"] = cells["old_premium"] * scale
        cells["new_premium_gbp"] = cells["new_premium"] * scale
        cells["change_amount_gbp"] = cells["change_amount"] * scale
    weighted = cells["exposure"]
    old, new = (weighted * cells["old_premium"]).sum(), (weighted * cells["new_premium"]).sum()
    unconstrained = (weighted * cells["old_premium"] * uncapped).sum()
    totals = {
        "exposure": float(weighted.sum()),
        "old_premium": float(old),
        "new_premium": float(new),
        "change_pct": float(100 * (new / old - 1)),
        "cap_floor_cost": float(unconstrained - new),
        "cells_capped": int(
            (uncapped - 1 > (scenario.cap if scenario.cap is not None else np.inf)).sum()
        ),
        "cells_floored": int(
            (uncapped - 1 < (scenario.floor if scenario.floor is not None else -np.inf)).sum()
        ),
    }
    if scale:
        totals["old_premium_gbp"], totals["new_premium_gbp"] = old * scale, new * scale
    return {"cells": cells, "totals": totals}


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order]) / weights.sum()
    return float(values[order][np.searchsorted(cumulative, q)])


def dislocation(cells: pd.DataFrame) -> pd.DataFrame:
    """The exposure-weighted distribution of premium changes by age group, region and conditions."""
    data = cells.copy()
    conditions = sum((data[c] == "1").astype(int) for c in CONDITIONS)
    data["age group"] = age_group(data["age"]).to_numpy()
    data["region"] = "region " + data["region"].astype(str)
    data["number of conditions"] = conditions.clip(upper=3).map(
        {0: "0", 1: "1", 2: "2", 3: "3 or more"}
    )
    rows = []
    for dimension in ("age group", "region", "number of conditions"):
        for level, part in data.groupby(dimension):
            change, weight = part["change_pct"].to_numpy(), part["exposure"].to_numpy()
            row = {"dimension": dimension, "segment": level, "exposure": float(weight.sum())}
            row["mean_change_pct"] = float(np.average(change, weights=weight))
            for q in QUANTILES:
                row[f"p{int(q * 100):02d}_change_pct"] = _weighted_quantile(change, weight, q)
            row["share_increase_over_10pct"] = float(weight[change > 10].sum() / weight.sum())
            rows.append(row)
    return pd.DataFrame(rows)


def save_histogram(cells: pd.DataFrame, path) -> None:
    """An exposure-weighted histogram of premium changes."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(cells["change_pct"], bins=30, weights=cells["exposure"], color="#3b6ea5")
    ax.set_xlabel("Premium change (percent)")
    ax.set_ylabel("Exposure (person-years)")
    ax.set_title("Premium change by exposure under the example scenario")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


EXAMPLE = Scenario(
    base_change=0.04,
    relativity_changes={("age", "75-79"): 0.05, ("age", "80+"): 0.10},
    cap=0.12,
    floor=0.0,
)


def save_all(model_version: str = "m6_draft") -> dict[str, pd.DataFrame]:
    """Build the book and the example scenario and save the tables and the histogram."""
    tariff = engine.load_tariff(model_version)
    directory = engine.OUTPUTS / model_version
    book = build_book()
    result = apply_scenario(book, EXAMPLE, tariff)
    tables = {
        "in_force_book.csv": book,
        "scenario_example_cells.csv": result["cells"],
        "scenario_example_totals.csv": pd.DataFrame([result["totals"]]),
        "scenario_example_dislocation.csv": dislocation(result["cells"]),
    }
    for name, table in tables.items():
        table.to_csv(directory / name, index=False)
    (directory / "figures").mkdir(exist_ok=True)
    save_histogram(result["cells"], directory / "figures" / "scenario_example_dislocation.png")
    return tables


if __name__ == "__main__":
    save_all()
