"""Evidence tables for the PMI-scope claim definition (decision gate 2, issue #8).

Run `uv run python -m health_pricing.evidence.pmi_scope` to print every table in markdown.
The tables are aggregated only. The proposal rules at the top are the single place the
proposed definition is written down, so the share it captures is computed, not typed in.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.data.sas_layout import extract_value_block

YEARS = {2022: "22", 2023: "23"}
LAYOUT_FILES = {
    "office_based": Path("data/raw/h239gsu.txt"),
    "outpatient": Path("data/raw/h239fsu.txt"),
    "inpatient": Path("data/raw/h239dsu.txt"),
}
COST_PREFIX = {"office_based": "OBXP", "outpatient": "OPXP", "inpatient": "IPXP"}
FYC_CATEGORIES = [
    ("Inpatient (facility and physician)", "IPTEXP"),
    ("Hospital outpatient", "OPTEXP"),
    ("Office-based", "OBVEXP"),
    ("Emergency room", "ERTEXP"),
    ("Prescribed medicines", "RXEXP"),
    ("Dental", "DVTEXP"),
]

# Proposed definition. Specialty codes are DRSPLTY_M18, visit categories are VSTCTGRY,
# non-doctor types are MEDPTYPE_M18 and inpatient reasons are RSNINHOS.
PRIMARY_CARE_SPECIALTIES = {
    6,
    8,
    14,
    24,
}  # family, general practice, internal medicine, paediatrics
UNKNOWN_SPECIALTIES = {-7, -8}
NON_DOCTOR_IN = {10, 13, 15}  # physical/occupational therapist, psychologist, technician
EXCLUDED_VISIT_CATEGORIES = {1, 6, 7, 8, 9, 10}  # check-up, shots, vision, pregnancy, child, laser
EXCLUDED_INPATIENT_REASONS = {4, 5, 6}  # birth (mother), baby, pregnancy complications


def value_labels(variable: str, event_type: str) -> dict[int, str]:
    """Code to label from the variable's VALUE block in AHRQ's SAS statements."""
    block = extract_value_block(LAYOUT_FILES[event_type], variable)
    labels = {}
    for line in block.splitlines():
        match = re.match(r'\s*(-?\d+)\s*=\s*"(?:-?\d+\s+)?(.*)"\s*$', line)
        if match:
            text = match.group(2).strip()
            text = "Don't know" if text == "DK" else text.lower().capitalize()
            labels[int(match.group(1))] = text
    return labels


def _sql_list(values: set[int]) -> str:
    return ", ".join(str(v) for v in sorted(values))


def in_scope_condition(event_type: str, include_er_stays: bool = False) -> str:
    """SQL condition that is true when an event is PMI-scope under the approved definition.

    Stays that began in the emergency room are out of the base definition (decision gate 2,
    2026-11-01). Pass include_er_stays=True for the sensitivity that puts them back in.
    """
    if event_type == "inpatient":
        condition = f"RSNINHOS NOT IN ({_sql_list(EXCLUDED_INPATIENT_REASONS)})"
        return condition if include_er_stays else f"{condition} AND EMERROOM <> 1"
    visit = f"VSTCTGRY NOT IN ({_sql_list(EXCLUDED_VISIT_CATEGORIES)})"
    doctor = f"(DRSPLTY_M18 > 0 AND DRSPLTY_M18 NOT IN ({_sql_list(PRIMARY_CARE_SPECIALTIES)}))"
    non_doctor = f"(DRSPLTY_M18 = -1 AND MEDPTYPE_M18 IN ({_sql_list(NON_DOCTOR_IN)}))"
    return f"({doctor} OR {non_doctor}) AND {visit}"


def level_is_in(event_type: str, variable: str, code: int) -> bool | None:
    """Whether a level is in scope on its own. None when it depends on another variable."""
    if event_type == "inpatient":
        return code not in EXCLUDED_INPATIENT_REASONS
    if variable == "VSTCTGRY":
        return code not in EXCLUDED_VISIT_CATEGORIES
    if variable == "DRSPLTY_M18":
        if code == -1:
            return None
        return code > 0 and code not in PRIMARY_CARE_SPECIALTIES
    if variable == "MEDPTYPE_M18":
        return code in NON_DOCTOR_IN
    raise ValueError(variable)


def definition_table(event_type: str, variable: str) -> pd.DataFrame:
    rows = []
    for code, label in sorted(value_labels(variable, event_type).items()):
        verdict = level_is_in(event_type, variable, code)
        if verdict is None:
            text = "Decided by type seen"
        else:
            text = "In" if verdict else "Out"
        rows.append((code, label, text))
    return pd.DataFrame(rows, columns=["Code", "Level", "Proposal"])


def claimant_table(
    con: duckdb.DuckDBPyConnection, year: int, include_er_stays: bool = False
) -> pd.DataFrame:
    s = YEARS[year]
    union = " UNION ".join(
        f"SELECT DUPERSID FROM raw.{t}_{year} WHERE {in_scope_condition(t, include_er_stays)}"
        for t in ("inpatient", "outpatient", "office_based")
    )
    claimants = con.execute(f"SELECT COUNT(*) FROM ({union})").fetchone()[0]
    persons = con.execute(f"SELECT COUNT(*) FROM raw.fyc_{year}").fetchone()[0]
    in_scope_persons = con.execute(
        f"SELECT COUNT(*) FROM raw.fyc_{year} WHERE PERWT{s}F > 0"
    ).fetchone()[0]
    return pd.DataFrame(
        [(persons, in_scope_persons, claimants, claimants / persons)],
        columns=["Persons", "Persons with a positive weight", "Persons with a claim", "Share"],
    )


def fyc_category_table(con: duckdb.DuckDBPyConnection, year: int) -> pd.DataFrame:
    s = YEARS[year]
    total = con.execute(f"SELECT SUM(TOTEXP{s}) FROM raw.fyc_{year}").fetchone()[0]
    total_w = con.execute(f"SELECT SUM(TOTEXP{s} * PERWT{s}F) FROM raw.fyc_{year}").fetchone()[0]
    rows = []
    explicit = ""
    for label, col in FYC_CATEGORIES:
        col_s = f"{col}{s}"
        persons, cost, cost_w = con.execute(
            f"SELECT COUNT(*) FILTER (WHERE {col_s} > 0), SUM({col_s}), SUM({col_s} * PERWT{s}F) "
            f"FROM raw.fyc_{year}"
        ).fetchone()
        rows.append((label, persons, cost, cost / total, cost_w / total_w))
        explicit += f" - {col_s}"
    other, other_w = con.execute(
        f"SELECT SUM(TOTEXP{s}{explicit}), SUM((TOTEXP{s}{explicit}) * PERWT{s}F) "
        f"FROM raw.fyc_{year}"
    ).fetchone()
    rows.append(
        (
            "Other (home health, glasses, other medical)",
            None,
            other,
            other / total,
            other_w / total_w,
        )
    )
    rows.append(("Total", None, total, 1.0, 1.0))
    return pd.DataFrame(
        rows, columns=["Category", "Persons with spend", "Cost", "Share of cost", "Weighted share"]
    )


def event_type_table(con: duckdb.DuckDBPyConnection, year: int) -> pd.DataFrame:
    s = YEARS[year]
    rows = []
    for event_type, label in (
        ("inpatient", "Inpatient stays"),
        ("outpatient", "Hospital outpatient visits"),
        ("office_based", "Office-based visits"),
    ):
        cost = f"{COST_PREFIX[event_type]}{s}X"
        table = f"raw.{event_type}_{year}"
        events, persons, total = con.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT DUPERSID), SUM({cost}) FROM {table}"
        ).fetchone()
        rows.append((label, events, persons, total, total / events))
        if event_type == "inpatient":
            e, p, c = con.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT DUPERSID), SUM({cost}) FROM {table} "
                "WHERE EMERROOM = 1"
            ).fetchone()
            rows.append(("  of which began in the emergency room", e, p, c, c / e))
            e, p, c = con.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT DUPERSID), SUM({cost}) FROM {table} "
                f"WHERE RSNINHOS IN ({_sql_list(EXCLUDED_INPATIENT_REASONS)})"
            ).fetchone()
            rows.append(("  of which birth or pregnancy related", e, p, c, c / e))
    return pd.DataFrame(rows, columns=["Event type", "Events", "Persons", "Cost", "Cost per event"])


def breakdown_table(event_type: str, variable: str, where: str = "TRUE") -> pd.DataFrame:
    """Events and share of the event file's cost by level, both years side by side."""
    labels = value_labels(variable, event_type)
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    frames = []
    try:
        for year, s in YEARS.items():
            cost = f"{COST_PREFIX[event_type]}{s}X"
            df = con.execute(
                f"SELECT {variable} AS code, COUNT(*) AS events, SUM({cost}) AS cost "
                f"FROM raw.{event_type}_{year} WHERE {where} GROUP BY 1"
            ).df()
            df["share"] = df["cost"] / df["cost"].sum()
            frames.append(df.set_index("code")[["events", "share"]].add_suffix(f" {year}"))
    finally:
        con.close()
    out = pd.concat(frames, axis=1).fillna(0).sort_values("share 2023", ascending=False)
    for year in YEARS:
        out[f"events {year}"] = out[f"events {year}"].astype(int)
    out.insert(0, "Level", [f"{c} {labels.get(c, '')}".strip() for c in out.index])
    return out.reset_index(drop=True)


def captured_share_table(
    con: duckdb.DuckDBPyConnection, year: int, include_er_stays: bool = False
) -> pd.DataFrame:
    s = YEARS[year]
    total = con.execute(f"SELECT SUM(TOTEXP{s}) FROM raw.fyc_{year}").fetchone()[0]
    rows = []
    for event_type, label in (
        ("inpatient", "Inpatient stays"),
        ("outpatient", "Hospital outpatient visits"),
        ("office_based", "Office-based visits"),
    ):
        cost = f"{COST_PREFIX[event_type]}{s}X"
        table = f"raw.{event_type}_{year}"
        all_events, all_cost = con.execute(f"SELECT COUNT(*), SUM({cost}) FROM {table}").fetchone()
        n, c, p = con.execute(
            f"SELECT COUNT(*), SUM({cost}), COUNT(DISTINCT DUPERSID) FROM {table} "
            f"WHERE {in_scope_condition(event_type, include_er_stays)}"
        ).fetchone()
        rows.append((label, all_events, n, all_cost, c, c / all_cost, c / total, p))
    df = pd.DataFrame(
        rows,
        columns=[
            "Event type",
            "All events",
            "In-scope events",
            "All cost",
            "In-scope cost",
            "Share of event-type cost",
            "Share of TOTEXP",
            "Persons with a claim",
        ],
    )
    sums = df[
        ["All events", "In-scope events", "All cost", "In-scope cost", "Persons with a claim"]
    ].sum()
    df.loc[len(df)] = [
        "Total",
        sums["All events"],
        sums["In-scope events"],
        sums["All cost"],
        sums["In-scope cost"],
        sums["In-scope cost"] / sums["All cost"],
        sums["In-scope cost"] / total,
        None,
    ]
    return df


def er_sensitivity_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Captured share and claimant share with ER-originated stays out (base) and in."""
    rows = []
    for year in YEARS:
        for label, include in (("Out (base)", False), ("In (sensitivity)", True)):
            total = captured_share_table(con, year, include).iloc[-1]
            claimants = claimant_table(con, year, include).iloc[0]
            rows.append(
                (
                    str(year),
                    label,
                    total["In-scope cost"],
                    total["Share of event-type cost"],
                    total["Share of TOTEXP"],
                    claimants["Share"],
                )
            )
    return pd.DataFrame(
        rows,
        columns=[
            "Year",
            "ER-originated stays",
            "In-scope cost",
            "Share of the three event files",
            "Share of TOTEXP",
            "Persons with a claim",
        ],
    )


def to_markdown(df: pd.DataFrame) -> str:
    def fmt(value):
        if pd.isna(value):
            return ""
        if isinstance(value, float):
            return f"{value:.1%}" if abs(value) <= 1.0 else f"{value:,.0f}"
        if isinstance(value, int | float) or hasattr(value, "item"):
            return f"{value:,}"
        return str(value)

    header = "| " + " | ".join(df.columns) + " |"
    rule = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([header, rule, *body])


def _section(title: str, table: pd.DataFrame) -> None:
    print()
    print(f"### {title}")
    print()
    print(to_markdown(table))


def main() -> None:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        for year in YEARS:
            _section(f"FYC spending by category, {year}", fyc_category_table(con, year))
        for year in YEARS:
            _section(f"Event files, {year}", event_type_table(con, year))
        for year in YEARS:
            _section(f"Share captured by the proposal, {year}", captured_share_table(con, year))
        for year in YEARS:
            _section(f"Persons with an in-scope claim, {year}", claimant_table(con, year))
        _section("Sensitivity: ER-originated stays out (base) and in", er_sensitivity_table(con))
    finally:
        con.close()
    for title, event_type, variable, where in (
        ("Office-based by doctor specialty", "office_based", "DRSPLTY_M18", "TRUE"),
        ("Office-based by visit category", "office_based", "VSTCTGRY", "TRUE"),
        ("Office-based, non-doctor visits", "office_based", "MEDPTYPE_M18", "DRSPLTY_M18 = -1"),
        ("Hospital outpatient by doctor specialty", "outpatient", "DRSPLTY_M18", "TRUE"),
        ("Hospital outpatient by visit category", "outpatient", "VSTCTGRY", "TRUE"),
        (
            "Hospital outpatient, non-doctor visits",
            "outpatient",
            "MEDPTYPE_M18",
            "DRSPLTY_M18 = -1",
        ),
        ("Inpatient by reason for stay", "inpatient", "RSNINHOS", "TRUE"),
    ):
        _section(title, breakdown_table(event_type, variable, where))
    for title, event_type, variable in (
        ("Proposal: doctor specialty (DRSPLTY_M18)", "office_based", "DRSPLTY_M18"),
        ("Proposal: visit category (VSTCTGRY)", "office_based", "VSTCTGRY"),
        ("Proposal: type seen when not a doctor (MEDPTYPE_M18)", "office_based", "MEDPTYPE_M18"),
        ("Proposal: inpatient reason for stay (RSNINHOS)", "inpatient", "RSNINHOS"),
    ):
        _section(title, definition_table(event_type, variable))


if __name__ == "__main__":
    main()
