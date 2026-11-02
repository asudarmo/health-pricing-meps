"""Leakage check on the `unknown` level of the adult-only questions (issue #25).

An adult is `unknown` on a question when they were never asked, for example because they left the
survey before the round or died before the section. That may make `unknown` an indicator of
leaving or dying, which a rating factor must not be. These tables compare `unknown` adults with
adults who answered. They use the 2022 train split only and return aggregates.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH

# Every candidate factor that has an `unknown` level: the smoking and exercise questions, the nine
# adult-only condition flags, and the two condition flags asked at any age.
UNKNOWN_VARIABLES = [
    "OFTSMK53", "PHYEXE53", "HIBPDX", "CHDDX", "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX",
    "CANCERDX", "ARTHDX", "ASTHDX", "DIABDX_M18",
]  # fmt: skip
PLACEHOLDERS = ("unknown", "not_applicable")
ADULT_AGE = 18


def load_leakage_frame(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """Adults in the 2022 train split, with the columns the tables need."""
    own = con is None
    con = con or duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        columns = ", ".join(UNKNOWN_VARIABLES)
        return con.execute(
            f"SELECT age, left_survey_early, exposure, claim_count, "
            f"claim_cost_2023_prices AS cost, {columns} FROM mart_person_year "
            f"WHERE year = 2022 AND split = 'train' AND age >= {ADULT_AGE}"
        ).fetchdf()
    finally:
        if own:
            con.close()


def _group(series: pd.Series, name: str) -> pd.Series:
    """True for the rows in the group: `unknown`, or answered (a real answer, not a placeholder)."""
    if name == "unknown":
        return series == "unknown"
    return series.notna() & ~series.isin(PLACEHOLDERS)


def _profile(rows: pd.DataFrame) -> dict[str, float]:
    claimants = rows["claim_count"] > 0
    exposure = rows["exposure"].sum()
    return {
        "person_years": len(rows),
        "mean_age": rows["age"].mean(),
        "share_under_25": (rows["age"] < 25).mean(),
        "share_left_survey_early": rows["left_survey_early"].mean(),
        "share_exposure_under_1": (rows["exposure"] < 1).mean(),
        "mean_exposure": rows["exposure"].mean(),
        "claimant_rate": claimants.mean(),
        "mean_cost_per_claimant": rows.loc[claimants, "cost"].mean(),
        "cost_per_exposure_year": rows["cost"].sum() / exposure if exposure else float("nan"),
    }


def unknown_level_table(frame: pd.DataFrame, variables: list[str] = UNKNOWN_VARIABLES):
    """For each variable, adults at `unknown` against adults who answered."""
    rows = []
    for variable in variables:
        for name in ("unknown", "answered"):
            group = frame[_group(frame[variable], name)]
            rows.append({"variable": variable, "group": name, **_profile(group)})
    return pd.DataFrame(rows)


def unknown_by_leaver_table(frame: pd.DataFrame, variables: list[str] = UNKNOWN_VARIABLES):
    """The other direction. The share of leavers who are `unknown`, against the share of stayers."""
    rows = []
    for variable in variables:
        in_scope = frame[_group(frame[variable], "unknown") | _group(frame[variable], "answered")]
        unknown = in_scope[variable] == "unknown"
        leaver = in_scope["left_survey_early"].astype(bool)
        rows.append(
            {
                "variable": variable,
                "leavers": int(leaver.sum()),
                "leavers_unknown_share": unknown[leaver].mean() if leaver.any() else float("nan"),
                "stayers_unknown_share": unknown[~leaver].mean(),
            }
        )
    return pd.DataFrame(rows)


def merge_effect_table(frame: pd.DataFrame, variables: list[str] = UNKNOWN_VARIABLES):
    """What merging `unknown` into the reference level would do to the reference level's cost.

    The reference is the answered level with the most exposure. Cost is per exposure year. A large
    rise means the `unknown` person-years would distort the reference, and so every relativity.
    """
    rows = []
    for variable in variables:
        answered = frame[_group(frame[variable], "answered")]
        reference = answered.groupby(variable)["exposure"].sum().idxmax()
        ref_rows = answered[answered[variable] == reference]
        unknown = frame[_group(frame[variable], "unknown")]
        before = ref_rows["cost"].sum() / ref_rows["exposure"].sum()
        exposure = ref_rows["exposure"].sum() + unknown["exposure"].sum()
        after = (ref_rows["cost"].sum() + unknown["cost"].sum()) / exposure
        rows.append(
            {
                "variable": variable,
                "reference_level": reference,
                "unknown_share_of_reference_exposure": unknown["exposure"].sum()
                / ref_rows["exposure"].sum(),
                "reference_cost_per_exposure_year": before,
                "cost_after_merge": after,
                "change_after_merge": after / before - 1,
            }
        )
    return pd.DataFrame(rows)
