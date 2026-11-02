"""Sensitivity: add the stays that began in the emergency room to the PMI-scope claims (M5, #49).

The approved PMI-scope definition leaves out inpatient stays that began in the emergency room
(decision gate 2). This module adds them back, as a sensitivity only. The broadened cost of a
person-year is its base cost plus its ER-originated stay cost, on the same 2023 price basis, and a
person with an ER-originated stay is a claimant. The base definition stays the approved one.

The frozen base model is scored against the broadened 2023 cost, and the same structure is refitted
on 2022 train with the broadened cost, for comparison. The large-claim cap is kept at the same
dollar amount, and the provisional load is not re-estimated.
"""

from __future__ import annotations

import dataclasses

import duckdb
import numpy as np
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import frame as mf
from health_pricing.models import monitoring, outofsample, relativities, stability, trend
from health_pricing.models.frame import FACTORS

ER_COLUMNS = "er_stay_count, er_stay_cost_2023_prices"


def load_mart(year: int, split: list[str], con: duckdb.DuckDBPyConnection | None = None):
    """Mart rows of a year and splits, with the base and the ER-originated stay columns."""
    own = con is None
    con = con or duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        splits = ", ".join(f"'{s}'" for s in split)
        return con.execute(
            f"SELECT DUPERSID, DUID, year, split, {', '.join(FACTORS)}, exposure, claim_count, "
            f"claim_cost_2023_prices, {ER_COLUMNS} FROM mart_person_year "
            f"WHERE year = {year} AND split IN ({splits})"
        ).fetchdf()
    finally:
        if own:
            con.close()


def broaden(mart: pd.DataFrame) -> pd.DataFrame:
    """The mart rows with the claim count and cost including the ER-originated stays."""
    out = mart.copy()
    out["claim_count"] = mart["claim_count"] + mart["er_stay_count"]
    out["claim_cost_2023_prices"] = (
        mart["claim_cost_2023_prices"] + mart["er_stay_cost_2023_prices"]
    )
    return out


@dataclasses.dataclass
class Sensitivity:
    """The base model, the model refitted on the broadened cost, and the broadened 2023 frame."""

    base: outofsample.FrozenModel
    broad: outofsample.FrozenModel
    base_oot: outofsample.OutOfTime
    broad_oot: outofsample.OutOfTime
    mart_2022: pd.DataFrame
    mart_2023: pd.DataFrame


def build(base: outofsample.FrozenModel, base_oot: outofsample.OutOfTime) -> Sensitivity:
    """Refit the final structure on the broadened 2022 train cost, and build the 2023 frame."""
    mart_2022 = load_mart(mf.MODEL_YEAR, ["train", "test"])
    mart_2023 = load_mart(outofsample.OUT_OF_TIME_YEAR, [outofsample.OUT_OF_TIME_SPLIT])
    raw = mf.build_frames(broaden(mart_2022))
    broad = outofsample.freeze(raw)
    broad_oot = outofsample.group_out_of_time(broad, broaden(mart_2023))
    return Sensitivity(base, broad, base_oot, broad_oot, mart_2022, mart_2023)


def _age_group(mart: pd.DataFrame) -> pd.Series:
    ages = mart["age"].astype(float).astype(int).to_numpy()
    return pd.Series(
        np.select([ages < 18, ages < 40, ages < 65], trend.AGE_GROUPS[:3], trend.AGE_GROUPS[3]),
        index=mart.index,
    )


def _percent(part: float, whole: float) -> float:
    return 100 * part / whole if whole else float("nan")


def added_by_age_group(mart: pd.DataFrame) -> pd.DataFrame:
    """Cost and claimants that the ER-originated stays add, by age group, for one year's rows.

    Cost added is the ER stay cost over the base cost. Claimants added are people whose only
    claims are ER-originated stays, over the base claimants. Both are exposure-unweighted counts
    of person-years, and the cost is in dollars at 2023 prices. Only aggregates are returned.
    """
    work = mart.assign(
        group=_age_group(mart),
        base_claimant=mart["claim_count"] > 0,
        er_claimant=mart["er_stay_count"] > 0,
    )
    work["new_claimant"] = work["er_claimant"] & ~work["base_claimant"]
    rows = []
    for group, part in [*work.groupby("group"), ("All", work)]:
        base_cost = part["claim_cost_2023_prices"].sum()
        added_cost = part["er_stay_cost_2023_prices"].sum()
        rows.append(
            {
                "age_group": group,
                "person_years": len(part),
                "base_cost": base_cost,
                "er_stay_cost": added_cost,
                "cost_added_pct": _percent(added_cost, base_cost),
                "base_claimants": int(part["base_claimant"].sum()),
                "claimants_with_er_stay": int(part["er_claimant"].sum()),
                "claimants_added": int(part["new_claimant"].sum()),
                "claimants_added_pct": _percent(
                    part["new_claimant"].sum(), part["base_claimant"].sum()
                ),
            }
        )
    out = pd.DataFrame(rows)
    order = {g: i for i, g in enumerate([*trend.AGE_GROUPS, "All"])}
    return out.sort_values("age_group", key=lambda c: c.map(order)).reset_index(drop=True)


def _with_cost(oot: outofsample.OutOfTime, cost: pd.Series) -> outofsample.OutOfTime:
    """The 2023 frame with its cost replaced, so the base predictions are scored against it."""
    return dataclasses.replace(
        oot,
        frame=oot.frame.assign(cost=cost.to_numpy()),
        spline_frame=oot.spline_frame.assign(cost=cost.to_numpy()),
    )


def score_against_broadened(
    sens: Sensitivity, factor: float, n_boot: int = monitoring.N_BOOT
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Overall A/E, A/E by age group and Gini of the base model on the base and broadened cost.

    The base model is the frozen one. Its predictions and the forecast trend are unchanged. Only
    the actual cost differs, so the A/E rises by the share that the ER stays add.
    """
    predictions = monitoring.forecast(sens.base, sens.base_oot, factor)
    by_person = sens.mart_2023.set_index("DUPERSID")
    total = by_person["claim_cost_2023_prices"] + by_person["er_stay_cost_2023_prices"]
    broadened = _with_cost(sens.base_oot, sens.base_oot.frame["DUPERSID"].map(total))
    overall, ages, gini = [], [], []
    for label, oot in (("Base definition", sens.base_oot), ("With ER-originated stays", broadened)):
        overall.append(monitoring.overall(oot, predictions, n_boot).assign(definition=label))
        ages.append(monitoring.by_age_group(oot, predictions, n_boot).assign(definition=label))
        table = monitoring.scores(sens.base, oot, predictions)
        gini.append(table[table["candidate"].isin(predictions)].assign(definition=label))
    return (
        pd.concat(overall, ignore_index=True),
        pd.concat(ages, ignore_index=True),
        pd.concat(gini, ignore_index=True),
    )


def score_refitted(
    sens: Sensitivity, factor: float, n_boot: int = monitoring.N_BOOT
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The model refitted on the broadened 2022 cost, scored on the broadened 2023 cost.

    This is the like-for-like A/E under the broader definition, where the level of the ER stays is
    already in the 2022 fit. The same forecast trend is applied.
    """
    predictions = monitoring.forecast(sens.broad, sens.broad_oot, factor)
    label = "Refitted on broadened 2022 cost"
    scores = monitoring.scores(sens.broad, sens.broad_oot, predictions)
    return (
        monitoring.overall(sens.broad_oot, predictions, n_boot).assign(definition=label),
        monitoring.by_age_group(sens.broad_oot, predictions, n_boot).assign(definition=label),
        scores[scores["candidate"].isin(predictions)].assign(definition=label),
    )


def _relabel(table: pd.DataFrame) -> pd.DataFrame:
    """Rename the 2022 and 2023 columns of a stability comparison to base and broadened."""
    return table.rename(columns=lambda c: c.replace("_2022", "_base").replace("_2023", "_broad"))


def relativity_comparison(sens: Sensitivity) -> pd.DataFrame:
    """Frequency, severity and combined relativities of the broadened fit over the base fit.

    Both are fitted on 2022 train and the broadened cost contains the base cost, so the two fits
    are strongly dependent. The intervals treat them as independent and are therefore wide.
    """
    parts = []
    base_frame = sens.base.final_tariff.frames["spline"].train
    broad_frame = sens.broad.final_tariff.frames["spline"].train
    for part in ("frequency", "severity"):
        earlier = relativities.component_table(sens.base.spline.model, base_frame, part)
        later = relativities.component_table(sens.broad.spline.model, broad_frame, part)
        parts.append((part, earlier, later))
    combined = (
        "combined",
        relativities.combined_table(parts[0][1], parts[1][1]),
        relativities.combined_table(parts[0][2], parts[1][2]),
    )
    rows = [
        _relabel(stability.compare(earlier, later)).assign(part=part)
        for part, earlier, later in [*parts, combined]
    ]
    out = pd.concat(rows, ignore_index=True)
    return out[["part", *[c for c in out.columns if c != "part"]]]


def factor_ranking(table: pd.DataFrame) -> pd.DataFrame:
    """Rank the rating factors by the largest combined relativity of any level, in each fit."""
    combined = table[(table["part"] == "combined") & (table["role"] == "rating")]
    out = combined.groupby("factor").agg(
        largest_base=("relativity_base", "max"), largest_broad=("relativity_broad", "max")
    )
    out["rank_base"] = out["largest_base"].rank(ascending=False, method="min").astype(int)
    out["rank_broad"] = out["largest_broad"].rank(ascending=False, method="min").astype(int)
    return out.sort_values("rank_base").reset_index()


def age_curves(sens: Sensitivity) -> pd.DataFrame:
    """The adult age curve of the base fit and the broadened fit against age 67."""
    refit = stability.Refit(
        sens.broad.spline.model, sens.broad.final_tariff.tariff, sens.broad.balance
    )
    return _relabel(stability.age_curve_comparison(sens.base, refit))
