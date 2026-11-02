"""Tests for the benefit-type split (issue #24).

Part one runs the model SQL on a throwaway dbt project with hand-made events. Part two tests the
summary functions on small tables. Part three checks the real built tables when they exist.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import benefit
from health_pricing.models.frame import FACTORS

REPO = Path(__file__).resolve().parents[1]
INTERMEDIATE = REPO / "dbt" / "models" / "intermediate"
MARTS = REPO / "dbt" / "models" / "marts"

IP_COLUMNS = "DUPERSID VARCHAR, EVNTIDX VARCHAR, IPXP{yy}X DOUBLE, RSNINHOS BIGINT, EMERROOM BIGINT"
VISIT_COLUMNS = (
    "DUPERSID VARCHAR, EVNTIDX VARCHAR, {prefix}{yy}X DOUBLE, DRSPLTY_M18 BIGINT, "
    "MEDPTYPE_M18 BIGINT, VSTCTGRY BIGINT, SURGPROC BIGINT"
)

# (person, year, split). p3 has no events at all.
PEOPLE = [
    ("p1", 2022, "train"),
    ("p2", 2022, "test"),
    ("p3", 2022, "train"),
    ("p1", 2023, "out_of_time"),
]
EVENTS = {
    "inpatient_2022": [
        ("p1", "i1", 1000.0, 1, 2),  # elective stay, in
        ("p1", "i2", 500.0, 2, 1),  # began in the ER, in neither benefit type
        ("p1", "i3", 900.0, 4, 2),  # birth, in neither
    ],
    "outpatient_2022": [
        ("p1", "o1", 200.0, -1, 15, 2, 1),  # technician with a procedure, day-case
        ("p1", "o2", 50.0, 19, -1, 2, 2),  # specialist, no procedure, outpatient
        ("p1", "o3", 70.0, 8, -1, 2, 1),  # general practice with a procedure, out of scope
        ("p1", "o4", 30.0, 19, -1, 2, -8),  # procedure flag unknown, outpatient
    ],
    "office_based_2022": [
        ("p1", "b1", 100.5, 19, -1, 2, 1),  # specialist office procedure, day-case
        ("p2", "b2", 20.0, 19, -1, 2, 2),  # specialist, outpatient
    ],
    "inpatient_2023": [],
    "outpatient_2023": [],
    "office_based_2023": [("p1", "b3", 10.0, 3, -1, 5, 2)],  # cardiology, outpatient
}


def _mart_stub_ddl() -> str:
    factor_columns = ", ".join(f"{f} VARCHAR" for f in FACTORS)
    return (
        "DUPERSID VARCHAR, DUID BIGINT, year BIGINT, split VARCHAR, exposure DOUBLE, "
        f"{factor_columns}"
    )


@pytest.fixture(scope="module")
def benefit_rows(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("benefit")
    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    shutil.copytree(REPO / "dbt" / "macros", project / "macros")
    (project / "dbt_project.yml").write_text(
        'name: "fixture_project"\nversion: "1.0.0"\nconfig-version: 2\nprofile: "fixture"\n'
        'model-paths: ["models"]\nmacro-paths: ["macros"]\n',
        encoding="utf-8",
    )
    db = tmp_path / "fixture.duckdb"
    (project / "profiles.yml").write_text(
        "fixture:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        f'      path: "{db.as_posix()}"\n',
        encoding="utf-8",
    )
    (project / "models" / "mart_person_year.sql").write_text("select * from main.fx_mart\n")
    for table in EVENTS:
        (project / "models" / f"stg_{table}.sql").write_text(f"select * from main.fx_{table}\n")
    (project / "models" / "price_index_factor.sql").write_text(
        "select 2022 as from_year, 2023 as to_year, 100.0 as index_2022, 110.0 as index_2023, "
        "1.1 as factor\n"
    )
    shutil.copy(INTERMEDIATE / "int_events_pmi.sql", project / "models" / "int_events_pmi.sql")
    shutil.copy(
        MARTS / "mart_person_year_benefit.sql", project / "models" / "mart_person_year_benefit.sql"
    )

    con = duckdb.connect(str(db))
    con.execute(f"CREATE TABLE main.fx_mart ({_mart_stub_ddl()})")
    factor_values = ", ".join("'x'" for _ in FACTORS)
    for person, year, split in PEOPLE:
        values = f"'{person}', 1, {year}, '{split}', 1.0, {factor_values}"
        con.execute(f"INSERT INTO main.fx_mart VALUES ({values})")
    for table, rows in EVENTS.items():
        kind, year = table.rsplit("_", 1)
        yy = year[2:]
        if kind == "inpatient":
            ddl, marks = IP_COLUMNS.format(yy=yy), "?, ?, ?, ?, ?"
        else:
            prefix = "OPXP" if kind == "outpatient" else "OBXP"
            ddl, marks = VISIT_COLUMNS.format(prefix=prefix, yy=yy), "?, ?, ?, ?, ?, ?, ?"
        con.execute(f"CREATE TABLE main.fx_{table} ({ddl})")
        if rows:
            con.executemany(f"INSERT INTO main.fx_{table} VALUES ({marks})", rows)
    con.close()

    run = subprocess.run(
        [sys.executable, "-m", "dbt.cli.main", "run", "--project-dir", str(project),
         "--profiles-dir", str(project)],
        capture_output=True, text=True, cwd=tmp_path,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    con = duckdb.connect(str(db), read_only=True)
    out = con.execute("SELECT * FROM mart_person_year_benefit").fetchdf()
    con.close()
    return out.set_index(["DUPERSID", "year", "benefit_type"])


def test_every_person_year_has_both_benefit_types_even_with_no_events(benefit_rows):
    assert len(benefit_rows) == 2 * len(PEOPLE)
    for person, year, _ in PEOPLE:
        assert {b for p, y, b in benefit_rows.index if (p, y) == (person, year)} == {
            "inpatient_daycase",
            "outpatient",
        }
    for kind in ("inpatient_daycase", "outpatient"):
        row = benefit_rows.loc[("p3", 2022, kind)]
        assert (row["event_count"], row["claimant"], row["cost"]) == (0, 0, 0)


def test_inpatient_stays_and_surgical_visits_are_day_case_and_other_visits_outpatient(benefit_rows):
    day = benefit_rows.loc[("p1", 2022, "inpatient_daycase")]
    assert (
        day["event_count"] == 3
    )  # elective stay, technician procedure, specialist office procedure
    assert day["cost"] == pytest.approx(1000.0 + 200.0 + 100.5)
    out = benefit_rows.loc[("p1", 2022, "outpatient")]
    assert out["event_count"] == 2  # specialist visit, and the visit with an unknown procedure flag
    assert out["cost"] == pytest.approx(50.0 + 30.0)


def test_events_out_of_scope_are_in_neither_benefit_type(benefit_rows):
    # the ER-originated stay, the birth stay and the general practice procedure
    total = benefit_rows.sort_index().loc["p1", 2022]["event_count"].sum()
    assert total == 5


def test_claimant_flags_costs_and_on_levelling(benefit_rows):
    day = benefit_rows.loc[("p1", 2022, "inpatient_daycase")]
    assert day["claimant"] == 1
    assert day["cost_2023_prices"] == pytest.approx(day["cost"] * 1.1)
    later = benefit_rows.loc[("p1", 2023, "outpatient")]
    assert (later["event_count"], later["cost_2023_prices"]) == (1, 10.0)
    assert benefit_rows.loc[("p1", 2023, "inpatient_daycase"), "claimant"] == 0
    assert benefit_rows.loc[("p2", 2022, "outpatient"), "claimant"] == 1


def test_the_split_and_exposure_are_carried_through(benefit_rows):
    assert benefit_rows.loc[("p2", 2022, "outpatient"), "split"] == "test"
    assert (benefit_rows["exposure"] == 1.0).all()


# --- Part two: the summary functions ----------------------------------------------------------


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE mart_person_year_benefit (year BIGINT, benefit_type VARCHAR, "
        "claimant INTEGER, event_count BIGINT, cost_2023_prices DOUBLE)"
    )
    c.executemany(
        "INSERT INTO mart_person_year_benefit VALUES (?, ?, ?, ?, ?)",
        [
            (2022, "inpatient_daycase", 1, 2, 300.0),
            (2022, "outpatient", 1, 3, 100.0),
            (2022, "outpatient", 0, 0, 0.0),
            (2023, "outpatient", 1, 1, 50.0),
        ],
    )
    c.execute(
        "CREATE TABLE int_events_pmi (year BIGINT, DUPERSID VARCHAR, EVNTIDX VARCHAR, "
        "event_type VARCHAR, cost DOUBLE, in_scope BOOLEAN, er_stay BOOLEAN, benefit_type VARCHAR)"
    )
    c.executemany(
        "INSERT INTO int_events_pmi VALUES (?, 'p', ?, ?, ?, ?, false, ?)",
        [
            (2022, "1", "inpatient", 1000.0, True, "inpatient_daycase"),
            (2022, "2", "outpatient", 200.0, True, "inpatient_daycase"),
            (2022, "3", "outpatient", 100.0, True, "outpatient"),
            (2022, "4", "office_based", 100.0, True, "outpatient"),
            (2022, "5", "office_based", 700.0, False, "inpatient_daycase"),
        ],
    )
    return c


def test_benefit_summary_totals_and_shares_within_each_year(con):
    table = benefit.benefit_summary(con).set_index(["year", "benefit_type"])
    day = table.loc[(2022, "inpatient_daycase")]
    assert (day["person_years"], day["claimants"], day["events"]) == (1, 1, 2)
    assert day["events_share"] == pytest.approx(2 / 5)
    assert day["cost_2023_prices_share"] == pytest.approx(300 / 400)
    assert table.loc[(2023, "outpatient"), "events_share"] == 1.0


def test_surgproc_shift_counts_only_moved_visits_never_stays_or_out_of_scope_events(con):
    table = benefit.surgproc_shift(con).set_index("event_type")
    assert table.loc["outpatient", "moved_events"] == 1
    assert table.loc["outpatient", "moved_cost"] == 200.0
    assert table.loc["office_based", "moved_events"] == 0
    total = table.loc["all in-scope events"]
    assert (total["events"], total["moved_events"]) == (4, 1)  # the stay is in the total, not moved
    assert total["cost"] == 1400.0
    assert total["moved_cost_share"] == pytest.approx(200 / 1400)
    assert table.index.tolist()[-1] == "all in-scope events"


# --- Part three: the real built tables ----------------------------------------------------------


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'mart_person_year_benefit'"
        ).fetchone()
        return row[0] == 1
    finally:
        con.close()


@pytest.mark.skipif(not _built(), reason="run dbt build")
def test_real_benefit_rows_sum_to_the_mart_and_both_years_have_both_types():
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        mart_rows = con.execute("SELECT COUNT(*) FROM mart_person_year").fetchone()[0]
        benefit_rows = con.execute("SELECT COUNT(*) FROM mart_person_year_benefit").fetchone()[0]
        differing = con.execute(
            "SELECT COUNT(*) FROM mart_person_year m JOIN ("
            "SELECT year, DUPERSID, SUM(event_count) n, SUM(cost) c, SUM(cost_2023_prices) c23 "
            "FROM mart_person_year_benefit GROUP BY ALL) b USING (year, DUPERSID) "
            "WHERE m.claim_count <> b.n OR ABS(m.claim_cost - b.c) > 1e-6 "
            "OR ABS(m.claim_cost_2023_prices - b.c23) > 1e-6"
        ).fetchone()[0]
        summary = benefit.benefit_summary(con)
        shift = benefit.surgproc_shift(con)
    finally:
        con.close()
    assert benefit_rows == 2 * mart_rows
    assert differing == 0
    assert set(summary["benefit_type"]) == {"inpatient_daycase", "outpatient"}
    assert set(summary["year"]) == {2022, 2023}
    total = shift[shift["event_type"] == "all in-scope events"]
    assert total["moved_events_share"].between(0, 1).all()
    assert total["moved_cost_share"].between(0, 1).all()
    assert isinstance(summary, pd.DataFrame)
