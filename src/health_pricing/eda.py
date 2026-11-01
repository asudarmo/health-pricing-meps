"""Aggregated tables for the EDA notebook (issue #21).

Every function returns an aggregate (one row per level or bin), never person-level rows. They read
`mart_person_year`. Frequency is claims per exposure year, severity is cost per claim at 2023
prices, and pure premium is claim cost per exposure year.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH

AGE_BAND_SQL = (
    "CASE WHEN age < 18 THEN '00-17' WHEN age < 25 THEN '18-24' WHEN age < 35 THEN '25-34' "
    "WHEN age < 45 THEN '35-44' WHEN age < 55 THEN '45-54' WHEN age < 65 THEN '55-64' "
    "WHEN age < 75 THEN '65-74' ELSE '75+' END"
)
REGION_SQL = (
    "CASE region WHEN 1 THEN '1 Northeast' WHEN 2 THEN '2 Midwest' WHEN 3 THEN '3 South' "
    "WHEN 4 THEN '4 West' END"
)
SEX_SQL = "CASE SEX WHEN 1 THEN 'Male' WHEN 2 THEN 'Female' END"
CONDITION_FLAGS = [
    "HIBPDX", "CHDDX", "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX", "CANCERDX", "ARTHDX",
    "ASTHDX", "DIABDX_M18",
]  # fmt: skip


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DUCKDB_PATH), read_only=True)


def _rates(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["frequency"] = frame["claim_count"] / frame["exposure"]
    frame["severity"] = frame["claim_cost"] / frame["claim_count"].where(frame["claim_count"] > 0)
    frame["pure_premium"] = frame["claim_cost"] / frame["exposure"]
    return frame


def by_level(
    con: duckdb.DuckDBPyConnection, level_sql: str, name: str, where: str = "TRUE"
) -> pd.DataFrame:
    """Persons, exposure, claims, frequency, severity and pure premium for each level."""
    frame = con.execute(
        f"SELECT {level_sql} AS {name}, COUNT(*) AS persons, SUM(exposure) AS exposure, "
        f"SUM(claim_count) AS claim_count, SUM(claim_cost_2023_prices) AS claim_cost "
        f"FROM mart_person_year WHERE {where} GROUP BY 1 ORDER BY 1"
    ).fetchdf()
    return _rates(frame)


def by_age_band(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return by_level(con, AGE_BAND_SQL, "age_band")


def by_sex(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return by_level(con, SEX_SQL, "sex")


def by_region(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return by_level(con, REGION_SQL, "region")


def by_condition(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Frequency for adults with and without each condition (the answered levels only)."""
    frames = []
    for flag in CONDITION_FLAGS:
        frame = by_level(con, flag, "level", f"{flag} IN ('0', '1') AND age >= 18")
        frame.insert(0, "condition", flag)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def exposure_distribution(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Persons by whole months of exposure (1 to 12)."""
    return con.execute(
        "SELECT ROUND(exposure * 12)::INTEGER AS months, COUNT(*) AS persons "
        "FROM mart_person_year GROUP BY 1 ORDER BY 1"
    ).fetchdf()


def zero_claim_share(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        "SELECT year, COUNT(*) AS persons, COUNT(*) FILTER (WHERE claim_count = 0) AS zero_claim, "
        "COUNT(*) FILTER (WHERE claim_count = 0) * 1.0 / COUNT(*) AS zero_claim_share "
        "FROM mart_person_year GROUP BY year ORDER BY year"
    ).fetchdf()


def claim_cost_distribution(
    con: duckdb.DuckDBPyConnection, bins_per_decade: int = 4
) -> pd.DataFrame:
    """Claimants by bins of annual claim cost at 2023 prices, equal width on a log10 scale."""
    return con.execute(
        f"SELECT FLOOR(LOG10(claim_cost_2023_prices) * {bins_per_decade}) / {bins_per_decade} "
        f"AS log10_low, COUNT(*) AS claimants FROM mart_person_year "
        f"WHERE claim_cost_2023_prices > 0 GROUP BY 1 ORDER BY 1"
    ).fetchdf()


def split_balance(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Persons, exposure and claim cost by year and split, with the share within each year."""
    frame = con.execute(
        "SELECT year, split, COUNT(*) AS persons, SUM(exposure) AS exposure, "
        "SUM(claim_count) AS claim_count, SUM(claim_cost_2023_prices) AS claim_cost "
        "FROM mart_person_year GROUP BY year, split ORDER BY year, split"
    ).fetchdf()
    for column in ("persons", "exposure", "claim_cost"):
        frame[f"{column}_share"] = frame[column] / frame.groupby("year")[column].transform("sum")
    return frame
