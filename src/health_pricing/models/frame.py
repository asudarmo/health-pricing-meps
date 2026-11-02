"""The modelling frames for M3 (issue #23).

Train is the 2022 `train` split and test is the 2022 `test` split of `mart_person_year`. The 2023
`out_of_time` rows are never loaded here, because they are held back for M5. A person-year is the
unit. `cost` is the annual PMI-scope cost at 2023 prices, `claimant` says whether it had at least
one claim, and `cost_per_claimant` is the cost for claimants only. The frames hold person-level
rows for fitting, so they must not be displayed or saved. The summary tables below are aggregates.
"""

from __future__ import annotations

import numbers
from dataclasses import dataclass

import duckdb
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH

# The rating factor candidates declared in dbt/models/marts/schema.yml (role rating_factor).
FACTORS = [
    "age", "region", "inscov", "rthlth", "mnhlth", "OFTSMK53", "PHYEXE53", "HIBPDX", "CHDDX",
    "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX", "CANCERDX", "ARTHDX", "ASTHDX", "DIABDX_M18",
]  # fmt: skip
# Levels that are never the reference, because they are not a real answer.
NOT_REFERENCE = ("not_applicable", "unknown")
MODEL_SPLITS = ("train", "test")
MODEL_YEAR = 2022


@dataclass
class Frames:
    train: pd.DataFrame
    test: pd.DataFrame
    reference_levels: dict[str, str]


def _level_key(level: str):
    """Numeric levels in numeric order, then the rest alphabetically."""
    try:
        return (0, int(level), "")
    except ValueError:
        return (1, 0, level)


def _as_text(series: pd.Series) -> pd.Series:
    """Factor values as text, with nulls kept as null. Numbers lose any trailing .0."""
    return series.map(lambda v: None if pd.isna(v) else str(int(v)) if _is_whole(v) else str(v))


def _is_whole(value: object) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool) and float(value) % 1 == 0


def reference_levels(train: pd.DataFrame, factors: list[str] = FACTORS) -> dict[str, str]:
    """For each factor the level with the most exposure, never `not_applicable` or `unknown`.

    Ties go to the level that sorts first, so the choice is the same on every run.
    """
    reference = {}
    for factor in factors:
        exposure = train.groupby(_as_text(train[factor]), dropna=True)["exposure"].sum()
        exposure = exposure.drop(list(NOT_REFERENCE), errors="ignore")
        ranked = sorted(exposure.items(), key=lambda item: (-item[1], _level_key(item[0])))
        reference[factor] = ranked[0][0]
    return reference


def _type_factors(
    frame: pd.DataFrame, reference: dict[str, str], categories: dict[str, list[str]]
) -> pd.DataFrame:
    frame = frame.copy()
    for factor in reference:
        frame[factor] = pd.Categorical(_as_text(frame[factor]), categories=categories[factor])
    return frame


def build_frames(mart: pd.DataFrame, factors: list[str] = FACTORS) -> Frames:
    """Train and test frames from mart rows. Only the 2022 `train` and `test` rows are used."""
    mart = mart[(mart["year"] == MODEL_YEAR) & mart["split"].isin(MODEL_SPLITS)].copy()
    mart["claimant"] = (mart["claim_count"] > 0).astype(int)
    mart["cost"] = mart["claim_cost_2023_prices"]
    mart["cost_per_claimant"] = mart["cost"].where(mart["claimant"] == 1)
    train = mart[mart["split"] == "train"].reset_index(drop=True)
    test = mart[mart["split"] == "test"].reset_index(drop=True)
    reference = reference_levels(train, factors)
    categories = {}
    for factor in factors:
        levels = set(_as_text(mart[factor]).dropna())
        others = sorted(levels - {reference[factor]}, key=_level_key)
        categories[factor] = [reference[factor], *others]
    return Frames(
        _type_factors(train, reference, categories),
        _type_factors(test, reference, categories),
        reference,
    )


def load_frames(con: duckdb.DuckDBPyConnection | None = None) -> Frames:
    """Load the modelling frames from the DuckDB database."""
    own = con is None
    con = con or duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        columns = ", ".join(FACTORS)
        mart = con.execute(
            f"SELECT DUPERSID, DUID, year, split, {columns}, exposure, claim_count, "
            f"claim_cost_2023_prices FROM mart_person_year "
            f"WHERE year = {MODEL_YEAR} AND split IN ('train', 'test')"
        ).fetchdf()
    finally:
        if own:
            con.close()
    return build_frames(mart)


def frame_summary(frames: Frames) -> pd.DataFrame:
    """Rows, exposure, claimants, claims and cost by split."""
    rows = []
    for name, frame in (("train", frames.train), ("test", frames.test)):
        rows.append(
            {
                "split": name,
                "person_years": len(frame),
                "exposure": frame["exposure"].sum(),
                "claimants": int(frame["claimant"].sum()),
                "claimant_rate": frame["claimant"].mean(),
                "zero_cost_claimants": int(((frame["claimant"] == 1) & (frame["cost"] == 0)).sum()),
                "claims": int(frame["claim_count"].sum()),
                "cost": frame["cost"].sum(),
                "mean_cost_per_claimant": frame["cost_per_claimant"].mean(),
            }
        )
    return pd.DataFrame(rows)


def reference_table(frames: Frames) -> pd.DataFrame:
    """The reference level of each factor with its share of train exposure."""
    total = frames.train["exposure"].sum()
    rows = []
    for factor, level in frames.reference_levels.items():
        share = frames.train.loc[frames.train[factor] == level, "exposure"].sum() / total
        rows.append({"factor": factor, "reference_level": level, "exposure_share": share})
    return pd.DataFrame(rows)
