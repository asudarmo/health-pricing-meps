"""Aggregate tables for the benefit-type split behind the stacked candidate (issue #24).

`mart_person_year_benefit` has one row per person-year per benefit type. Inpatient stays and any
in-scope outpatient or office-based visit with a surgical procedure (`SURGPROC` = 1) are
`inpatient_daycase`, all other in-scope visits are `outpatient`. Both functions return aggregates.
"""

from __future__ import annotations

import duckdb
import pandas as pd


def benefit_summary(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Person-years, claimants, events and cost (2023 prices) by year and benefit type."""
    frame = con.execute(
        "SELECT year, benefit_type, COUNT(*) AS person_years, SUM(claimant) AS claimants, "
        "SUM(event_count) AS events, SUM(cost_2023_prices) AS cost_2023_prices "
        "FROM mart_person_year_benefit GROUP BY year, benefit_type ORDER BY year, benefit_type"
    ).fetchdf()
    for column in ("events", "cost_2023_prices"):
        frame[f"{column}_share"] = frame[column] / frame.groupby("year")[column].transform("sum")
    return frame


def surgproc_shift(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """In-scope events and cost moved to inpatient_daycase by `SURGPROC`, by year and event file.

    The row `all in-scope events` of each year includes the inpatient stays in its totals, so its
    shares are of all in-scope events and cost. Only visits are ever moved. Cost is in dollars of
    the survey year.
    """
    moved = "(benefit_type = 'inpatient_daycase' AND event_type <> 'inpatient')"
    frame = con.execute(
        f"SELECT year, label AS event_type, COUNT(*) AS events, "
        f"COUNT(*) FILTER (WHERE moved) AS moved_events, SUM(cost) AS cost, "
        f"SUM(cost) FILTER (WHERE moved) AS moved_cost, "
        f"label = 'all in-scope events' AS is_total FROM ("
        f"SELECT year, event_type AS label, cost, {moved} AS moved "
        f"FROM int_events_pmi WHERE in_scope AND event_type <> 'inpatient' "
        f"UNION ALL SELECT year, 'all in-scope events', cost, {moved} "
        f"FROM int_events_pmi WHERE in_scope) GROUP BY year, label "
        f"ORDER BY year, is_total, label"
    ).fetchdf()
    frame = frame.drop(columns="is_total")
    frame["moved_events_share"] = frame["moved_events"] / frame["events"]
    frame["moved_cost_share"] = frame["moved_cost"] / frame["cost"]
    return frame
