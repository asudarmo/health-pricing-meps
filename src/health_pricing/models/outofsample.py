"""The frozen final model and the 2023 scoring frame for the out-of-time test (M5, issue #42).

The model is frozen from M3. The **technical model** is candidate (a) with the 9 rating factors.
The analysis-only factors (smoking, self-rated health, exercise and `inscov`) are priced at their
reference level, adult age is a natural spline and the base rate is rebalanced on 2022 train. The
**tariff** is its surrogate model (tariff) with five-year age bands, which is what would be
charged. Both are fitted on the 2022 `train` split only. The 2023 `out_of_time` rows are scored
and are never used to fit anything here. Costs of 2023 are as recorded, and the 2022 costs are
already on-levelled to 2023 prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import agecurve, factors, glm, large_claims, levels
from health_pricing.models import frame as mf
from health_pricing.models.frame import FACTORS, Frames

OUT_OF_TIME_YEAR = 2023
OUT_OF_TIME_SPLIT = "out_of_time"
OUTPUT_DIR = glm.SCORES_DIR.parent / "m5_draft"
TECHNICAL = "(a) Technical model"
TARIFF = "(a) Tariff"


@dataclass
class FrozenModel:
    """The technical model and the tariff, fitted on 2022 train."""

    raw: Frames  # 2022 frames before grouping, with age in years
    prepared: Frames  # 2022 frames with the approved grouping and the cap
    grouping: levels.Grouping
    final_tariff: agecurve.FinalTariff
    balance: float  # the factor that makes train predicted cost equal train actual cost
    controls: list[str]

    @property
    def spline(self) -> agecurve.AgeModel:
        return self.final_tariff.models["spline"]

    def technical(self, frame: pd.DataFrame) -> np.ndarray:
        """Technical model prediction for a frame that has the spline terms, rebalanced."""
        return self.spline.raw(frame) * self.balance

    def tariff(self, frame: pd.DataFrame) -> np.ndarray:
        """Tariff prediction for any frame with the grouped factors, exposure and age bands."""
        return self.final_tariff.tariff.predict(frame)

    def predictions(self, frame: pd.DataFrame) -> dict[str, np.ndarray]:
        """Both models' predicted annual cost (with the load) for a frame with spline terms."""
        return {TECHNICAL: self.technical(frame), TARIFF: self.tariff(frame)}


def freeze(raw: Frames | None = None) -> FrozenModel:
    """Fit the technical model and the tariff on 2022 train, as in M3."""
    raw = mf.load_frames() if raw is None else raw
    prepared = glm.prepare_frames(raw)
    final_tariff = agecurve.final_tariff(prepared, raw)
    spline = final_tariff.models["spline"]
    train = final_tariff.frames["spline"].train
    balance = factors.rebalance_factor(train, spline.raw(train))
    return FrozenModel(
        raw=raw,
        prepared=prepared,
        grouping=levels.decided_grouping(raw),
        final_tariff=final_tariff,
        balance=balance,
        controls=factors.controls_for("final"),
    )


@dataclass
class OutOfTime:
    """The 2023 rows, grouped and capped, with and without the spline terms."""

    frame: pd.DataFrame  # grouped factors, exposure, cost, capped_cost, with age bands
    spline_frame: pd.DataFrame  # the same rows with the spline terms and the child and adult bands
    new_levels: pd.DataFrame  # levels in 2023 that the grouping has not seen


def _load_mart(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    own = con is None
    con = con or duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        columns = ", ".join(FACTORS)
        return con.execute(
            f"SELECT DUPERSID, DUID, year, split, {columns}, exposure, claim_count, "
            f"claim_cost_2023_prices, er_stay_count, er_stay_cost_2023_prices "
            f"FROM mart_person_year WHERE year = {OUT_OF_TIME_YEAR} "
            f"AND split = '{OUT_OF_TIME_SPLIT}'"
        ).fetchdf()
    finally:
        if own:
            con.close()


def group_out_of_time(frozen: FrozenModel, mart: pd.DataFrame) -> OutOfTime:
    """Apply the M3 grouping to the 2023 rows.

    A level that the grouping has not seen goes to the reference.

    New levels are listed in `new_levels` with their row counts, so that none is hidden.
    """
    frame = mart.copy().reset_index(drop=True)
    ages = frame["age"].astype(float).astype(int).to_numpy()
    frame["claimant"] = (frame["claim_cost_2023_prices"] > 0).astype(int)
    frame["cost"] = frame["claim_cost_2023_prices"]
    frame["capped_cost"] = large_claims.capped_cost(frame["cost"])
    unseen = []
    for factor in FACTORS:
        text = levels.level_series(frame, factor)
        mapping = frozen.grouping.mapping[factor]
        group = text.map(mapping)
        missing = group.isna()
        if missing.any():
            for level, count in text[missing].value_counts().items():
                unseen.append(
                    {
                        "factor": factor,
                        "level": level,
                        "rows": int(count),
                        "treated_as": frozen.grouping.reference[factor],
                    }
                )
            group = group.fillna(frozen.grouping.reference[factor])
        categories = list(frozen.prepared.train[factor].cat.categories)
        frame[factor] = pd.Categorical(group, categories=categories)
    new_levels = pd.DataFrame(unseen, columns=["factor", "level", "rows", "treated_as"])
    # `with_spline` needs the age bands and the age in years
    spline = frozen.spline
    spline_frame = agecurve.with_spline(frame, ages, spline.knots, spline.df)
    return OutOfTime(frame, spline_frame, new_levels)


def load_out_of_time(
    frozen: FrozenModel, con: duckdb.DuckDBPyConnection | None = None
) -> OutOfTime:
    """The 2023 scoring frame, built from the mart and grouped as in M3."""
    return group_out_of_time(frozen, _load_mart(con))


def period_summary(frozen: FrozenModel, oot: OutOfTime) -> pd.DataFrame:
    """2023 next to 2022 train and test, and the cost above the large-claim cap.

    Cost per exposure year is on the 2023 price basis. The excess is the part of each person-year's
    cost above the cap, and the excess load is the excess over the capped cost.
    """
    rows = []
    for name, frame in (
        ("2022 train", frozen.prepared.train),
        ("2022 test", frozen.prepared.test),
        ("2023", oot.frame),
    ):
        capped = frame["capped_cost"].sum()
        cost = frame["cost"].sum()
        claimants = frame["capped_cost"] > 0
        rows.append(
            {
                "period": name,
                "person_years": len(frame),
                "exposure": frame["exposure"].sum(),
                "claimants": int(claimants.sum()),
                "claimant_rate": claimants.mean(),
                "cost_per_exposure_year": cost / frame["exposure"].sum(),
                "mean_cost_per_claimant": cost / claimants.sum(),
                "claimants_above_cap": int((frame["cost"] > large_claims.LARGE_CLAIM_CAP).sum()),
                "share_of_cost_above_cap": (cost - capped) / cost,
                "excess_load": (cost - capped) / capped,
            }
        )
    out = pd.DataFrame(rows)
    out["cost_per_exposure_year_vs_2022_train"] = (
        out["cost_per_exposure_year"] / out.loc[0, "cost_per_exposure_year"] - 1
    )
    return out


def save_table(table: pd.DataFrame, name: str, directory: Path = OUTPUT_DIR) -> Path:
    """Save an aggregate table under `outputs/m5_draft/`."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    table.to_csv(path, index=False)
    return path
