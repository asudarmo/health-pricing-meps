"""Tests for the PMI-scope claim counts and costs (issue #15).

Part one runs the model SQL on a throwaway dbt project with hand-made events. Part two checks the
real built tables: they agree with the Python rules in the evidence module, the event files
reconcile to the FYC category totals, and no person's claim cost exceeds their total spending.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.evidence import pmi_scope

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "dbt" / "models" / "intermediate"

# --- Part one: hand-made events -----------------------------------------------------------

IP_COLUMNS = "DUPERSID VARCHAR, EVNTIDX VARCHAR, IPXP{yy}X DOUBLE, RSNINHOS BIGINT, EMERROOM BIGINT"
VISIT_COLUMNS = (
    "DUPERSID VARCHAR, EVNTIDX VARCHAR, {prefix}{yy}X DOUBLE, DRSPLTY_M18 BIGINT, "
    "MEDPTYPE_M18 BIGINT, VSTCTGRY BIGINT"
)

PEOPLE = [
    (2022, "none"),
    (2022, "only_out"),
    (2022, "mixed"),
    (2023, "mixed"),
]
# (table, row). Costs have cents, as in the real files.
EVENTS = {
    "inpatient_2022": [
        ("only_out", "i1", 900.0, 4, 2),  # birth, out
        ("mixed", "i2", 1000.0, 1, 2),  # elective surgery, in
        ("mixed", "i3", 500.0, 2, 1),  # began in the ER, out of claims but in er_stay
        ("mixed", "i4", 300.0, 5, 1),  # baby stay that began in the ER, birth so in neither
    ],
    "outpatient_2022": [
        ("mixed", "o1", 40.25, -1, 15, 2),  # technician, in
        ("mixed", "o2", 60.0, -1, 8, 2),  # nurse, out
    ],
    "office_based_2022": [
        ("only_out", "b1", 80.0, 8, -1, 2),  # general practice, out
        ("only_out", "b2", 90.0, 19, -1, 1),  # specialist but general checkup, out
        ("mixed", "b3", 100.5, 19, -1, 2),  # specialist diagnosis, in
        ("mixed", "b4", 20.0, 6, -1, 2),  # family practice, out
    ],
    "inpatient_2023": [("mixed", "i5", 2000.0, 2, 2)],
    "outpatient_2023": [],
    "office_based_2023": [("mixed", "b5", 10.0, 3, -1, 5)],
}


@pytest.fixture(scope="module")
def claims(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("claims")
    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    shutil.copytree(REPO / "dbt" / "macros", project / "macros")
    (project / "dbt_project.yml").write_text(
        'name: "fixture_project"\nversion: "1.0.0"\nconfig-version: 2\nprofile: "fixture"\n'
        'model-paths: ["models"]\nmacro-paths: ["macros"]\n',
        encoding="utf-8",
    )
    db = tmp_path / "fixture.duckdb"
    profile = (
        "fixture:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        f'      path: "{db.as_posix()}"\n'
    )
    (project / "profiles.yml").write_text(profile, encoding="utf-8")
    (project / "models" / "int_person_clean.sql").write_text("select * from main.fx_people\n")
    for table in EVENTS:
        kind, year = table.rsplit("_", 1)
        (project / "models" / f"stg_{table}.sql").write_text(f"select * from main.fx_{table}\n")
    (project / "models" / "price_index_factor.sql").write_text(
        "select 2022 as from_year, 2023 as to_year, 100.0 as index_2022, 110.0 as index_2023, "
        "1.1 as factor\n"
    )
    for name in ("int_events_pmi", "int_person_claims"):
        shutil.copy(MODELS / f"{name}.sql", project / "models" / f"{name}.sql")

    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE main.fx_people (year BIGINT, DUPERSID VARCHAR)")
    con.executemany("INSERT INTO main.fx_people VALUES (?, ?)", PEOPLE)
    for table, rows in EVENTS.items():
        kind, year = table.rsplit("_", 1)
        yy = year[2:]
        if kind == "inpatient":
            ddl = IP_COLUMNS.format(yy=yy)
            marks = "?, ?, ?, ?, ?"
        else:
            prefix = "OPXP" if kind == "outpatient" else "OBXP"
            ddl = VISIT_COLUMNS.format(prefix=prefix, yy=yy)
            marks = "?, ?, ?, ?, ?, ?"
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
    out = con.execute("SELECT * FROM int_person_claims").fetchdf().set_index(["year", "DUPERSID"])
    con.close()
    return out


def test_a_person_with_no_events_is_kept_with_zeros(claims):
    row = claims.loc[(2022, "none")]
    assert (row["claim_count"], row["claim_cost"]) == (0, 0)
    assert (row["er_stay_count"], row["er_stay_cost"]) == (0, 0)


def test_a_person_with_only_out_of_scope_events_has_zeros(claims):
    row = claims.loc[(2022, "only_out")]
    assert (row["claim_count"], row["claim_cost"]) == (0, 0)


def test_a_person_with_a_mix_counts_only_the_in_scope_events(claims):
    row = claims.loc[(2022, "mixed")]
    assert row["claim_count"] == 3  # elective stay, technician visit, specialist visit
    assert row["claim_cost"] == pytest.approx(1000.0 + 40.25 + 100.5)


def test_er_originated_stays_are_kept_apart_and_birth_stays_are_in_neither(claims):
    row = claims.loc[(2022, "mixed")]
    assert row["er_stay_count"] == 1
    assert row["er_stay_cost"] == 500.0


def test_the_same_person_in_the_other_year_is_a_separate_row(claims):
    row = claims.loc[(2023, "mixed")]
    assert row["claim_count"] == 2  # the stay and a cardiology follow-up visit
    assert row["claim_cost"] == pytest.approx(2000.0 + 10.0)
    assert len(claims) == len(PEOPLE)


def test_2022_costs_are_on_levelled_and_2023_costs_are_unchanged(claims):
    row = claims.loc[(2022, "mixed")]
    assert row["claim_cost_2023_prices"] == pytest.approx(row["claim_cost"] * 1.1)
    assert row["er_stay_cost_2023_prices"] == pytest.approx(500.0 * 1.1)
    row = claims.loc[(2023, "mixed")]
    assert row["claim_cost_2023_prices"] == row["claim_cost"]


# --- Part two: the real built tables --------------------------------------------------------


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'int_person_claims'"
        ).fetchone()
        return row[0] == 1
    finally:
        con.close()


built = pytest.mark.skipif(not _built(), reason="run the load script and dbt build")


@built
@pytest.mark.parametrize("year", [2022, 2023])
def test_dbt_results_agree_with_the_python_rules_on_the_real_data(year):
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        python = pmi_scope.captured_share_table(con, year).set_index("Event type")
        sql = dict(
            con.execute(
                f"SELECT event_type, SUM(cost) FILTER (WHERE in_scope) "
                f"FROM int_events_pmi WHERE year = {year} GROUP BY 1"
            ).fetchall()
        )
        labels = {
            "inpatient": "Inpatient stays",
            "outpatient": "Hospital outpatient visits",
            "office_based": "Office-based visits",
        }
        for event_type, label in labels.items():
            assert sql[event_type] == pytest.approx(python.loc[label, "In-scope cost"], rel=1e-9)
        python_with_er = pmi_scope.captured_share_table(con, year, include_er_stays=True)
        er_cost = con.execute(
            f"SELECT SUM(er_stay_cost) FROM int_person_claims WHERE year = {year}"
        ).fetchone()[0]
        total_base = con.execute(
            f"SELECT SUM(claim_cost) FROM int_person_claims WHERE year = {year}"
        ).fetchone()[0]
        assert total_base + er_cost == pytest.approx(
            python_with_er.iloc[-1]["In-scope cost"], rel=1e-9
        )
    finally:
        con.close()


@built
@pytest.mark.parametrize("year", [2022, 2023])
def test_event_totals_reconcile_to_the_fyc_category_totals_within_1_percent(year):
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        for event_type, fyc_column in (
            ("inpatient", "IPTEXP"),
            ("outpatient", "OPTEXP"),
            ("office_based", "OBVEXP"),
        ):
            events = con.execute(
                "SELECT SUM(cost) FROM int_events_pmi WHERE year = ? AND event_type = ?",
                [year, event_type],
            ).fetchone()[0]
            fyc = con.execute(f"SELECT SUM({fyc_column}) FROM stg_fyc_{year}").fetchone()[0]
            assert abs(events - fyc) / fyc <= 0.01, (year, event_type, events, fyc)
    finally:
        con.close()


@built
def test_no_persons_claim_cost_exceeds_their_total_spending():
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        # Event costs carry cents and TOTEXP is a rounded dollar total, so a claim cost less
        # than one dollar over TOTEXP is allowed.
        worst = con.execute(
            "SELECT COUNT(*) FROM int_person_claims AS c JOIN int_person_clean AS p "
            "USING (year, DUPERSID) WHERE c.claim_cost >= p.TOTEXP + 1"
        ).fetchone()[0]
        assert worst == 0
    finally:
        con.close()


@built
def test_every_person_year_has_a_row_and_every_event_person_is_in_the_person_table():
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        rows = con.execute("SELECT COUNT(*) FROM int_person_claims").fetchone()[0]
        persons = con.execute("SELECT COUNT(*) FROM int_person_clean").fetchone()[0]
        assert rows == persons
        orphans = con.execute(
            "SELECT COUNT(*) FROM int_events_pmi e LEFT JOIN int_person_clean p "
            "USING (year, DUPERSID) WHERE p.DUPERSID IS NULL"
        ).fetchone()[0]
        assert orphans == 0
    finally:
        con.close()
