"""Reporting for the reserved-code treatment (issue #12).

Run `uv run python -m health_pricing.evidence.clean_checks` after `dbt build`. It prints the
agreement between the two age sources and the adult "unknown" level counts and cost share.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.evidence.pmi_scope import to_markdown

YEARS = {2022: "22", 2023: "23"}
LEVELLED = [
    "OFTSMK53", "PHYEXE53", "HIBPDX", "CHDDX", "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX",
    "CANCERDX", "ARTHDX", "ASTHDX", "DIABDX_M18",
]  # fmt: skip


def age_agreement_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Agreement of the year-end age and AGELAST for people who have both."""
    rows = []
    for year in YEARS:
        both, same, off_by_one = con.execute(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE AGELAST = age), "
            f"COUNT(*) FILTER (WHERE ABS(AGELAST - age) = 1) "
            f"FROM stg_fyc_{year} WHERE age >= 0 AND AGELAST >= 0"
        ).fetchone()
        missing, filled = con.execute(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE AGELAST >= 0) "
            f"FROM stg_fyc_{year} WHERE age < 0"
        ).fetchone()
        rows.append((str(year), both, same, same / both, off_by_one, missing, filled))
    return pd.DataFrame(
        rows,
        columns=[
            "Year",
            "People with both ages",
            "Equal",
            "Agreement rate",
            "Differ by one year",
            "Year-end age missing",
            "Filled from AGELAST",
        ],
    )


def unknown_level_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Adults (18+) whose answer is the 'unknown' level (a -1 code), with cost share."""
    rows = []
    for year in YEARS:
        total = con.execute(
            f"SELECT SUM(TOTEXP) FROM int_person_clean WHERE year = {year}"
        ).fetchone()[0]
        persons = con.execute(
            f"SELECT COUNT(*) FROM int_person_clean WHERE year = {year} AND age >= 18"
        ).fetchone()[0]
        for variable in LEVELLED:
            n, cost = con.execute(
                f"SELECT COUNT(*), SUM(TOTEXP) FROM int_person_clean "
                f"WHERE year = {year} AND age >= 18 AND {variable} = 'unknown'"
            ).fetchone()
            rows.append((str(year), variable, n, n / persons, cost or 0, (cost or 0) / total))
    return pd.DataFrame(
        rows,
        columns=[
            "Year",
            "Variable",
            "Adults unknown",
            "Share of adults",
            "TOTEXP",
            "Share of TOTEXP",
        ],
    )


def main() -> None:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        print("### Agreement between the year-end age and AGELAST\n")
        print(to_markdown(age_agreement_table(con)))
        print("\n### Adults with the 'unknown' level\n")
        print(to_markdown(unknown_level_table(con)))
    finally:
        con.close()


if __name__ == "__main__":
    main()
