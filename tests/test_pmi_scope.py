"""Tests for the PMI-scope evidence module (issue #8), on a tiny in-memory database."""

import duckdb
import pytest

from health_pricing.evidence import pmi_scope


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute("CREATE SCHEMA raw")
    c.execute(
        "CREATE TABLE raw.office_based_2022 AS SELECT * FROM (VALUES "
        "('A', 19, -1, 2, 100.0), "  # ophthalmology, diagnosis: in
        "('A', 6, -1, 2, 50.0), "  # family practice: out
        "('B', 3, -1, 1, 70.0), "  # cardiology but general checkup: out
        "('B', -1, 10, 2, 30.0), "  # physiotherapist: in
        "('C', -1, 8, 2, 20.0), "  # nurse: out
        "('C', -8, -1, 2, 10.0)"  # unknown specialty: out
        ") t(DUPERSID, DRSPLTY_M18, MEDPTYPE_M18, VSTCTGRY, OBXP22X)"
    )
    c.execute(
        "CREATE TABLE raw.inpatient_2022 AS SELECT * FROM (VALUES "
        "('A', 1, 2, 1000.0), "  # elective surgery: in
        "('B', 4, 2, 500.0), "  # birth: out
        "('C', -8, 2, 200.0), "  # unknown reason: in
        "('D', 2, 1, 900.0)"  # began in the emergency room: out of the base definition
        ") t(DUPERSID, RSNINHOS, EMERROOM, IPXP22X)"
    )
    return c


def _in_scope_cost(con, event_type, cost_col):
    return con.execute(
        f"SELECT COALESCE(SUM({cost_col}), 0) FROM raw.{event_type}_2022 "
        f"WHERE {pmi_scope.in_scope_condition(event_type)}"
    ).fetchone()[0]


def test_office_based_rules(con):
    assert _in_scope_cost(con, "office_based", "OBXP22X") == 130.0


def test_inpatient_excludes_birth_and_er_stays_but_keeps_unknown_reason(con):
    assert _in_scope_cost(con, "inpatient", "IPXP22X") == 1200.0


def test_er_stays_come_back_in_the_sensitivity(con):
    sql = pmi_scope.in_scope_condition("inpatient", include_er_stays=True)
    total = con.execute(f"SELECT SUM(IPXP22X) FROM raw.inpatient_2022 WHERE {sql}").fetchone()[0]
    assert total == 2100.0


def test_level_is_in_matches_sql_rules():
    assert pmi_scope.level_is_in("office_based", "DRSPLTY_M18", 6) is False
    assert pmi_scope.level_is_in("office_based", "DRSPLTY_M18", 19) is True
    assert pmi_scope.level_is_in("office_based", "DRSPLTY_M18", -8) is False
    assert pmi_scope.level_is_in("office_based", "DRSPLTY_M18", -1) is None
    assert pmi_scope.level_is_in("office_based", "VSTCTGRY", 1) is False
    assert pmi_scope.level_is_in("office_based", "VSTCTGRY", 91) is True
    assert pmi_scope.level_is_in("office_based", "MEDPTYPE_M18", 10) is True
    assert pmi_scope.level_is_in("office_based", "MEDPTYPE_M18", 8) is False
    assert pmi_scope.level_is_in("inpatient", "RSNINHOS", 4) is False


def test_to_markdown_formats_shares_and_counts():
    import pandas as pd

    table = pd.DataFrame({"Level": ["x"], "Events": [1234], "Share": [0.256]})
    assert "| x | 1,234 | 25.6% |" in pmi_scope.to_markdown(table)


def test_outpatient_and_office_based_share_one_rule():
    assert pmi_scope.in_scope_condition("outpatient") == pmi_scope.in_scope_condition(
        "office_based"
    )


def test_non_physician_list_is_physio_psychologist_technician_only():
    # Approved at decision gate 2. Nurses (8) are out because MEPS has no specialist-nurse level.
    assert pmi_scope.NON_DOCTOR_IN == {10, 13, 15}
    assert pmi_scope.level_is_in("outpatient", "MEDPTYPE_M18", 15) is True
    assert pmi_scope.level_is_in("outpatient", "MEDPTYPE_M18", 8) is False


def test_outpatient_rule_on_a_fixture(con):
    con.execute(
        "CREATE TABLE raw.outpatient_2022 AS SELECT * FROM (VALUES "
        "('A', 20, -1, 2, 100.0), "  # orthopaedics, diagnosis: in
        "('A', 8, -1, 2, 40.0), "  # general practice: out
        "('B', -1, 15, 2, 25.0), "  # technician: in
        "('B', -1, 8, 2, 15.0), "  # nurse: out
        "('C', 28, -1, 1, 60.0)"  # psychiatrist but general checkup: out
        ") t(DUPERSID, DRSPLTY_M18, MEDPTYPE_M18, VSTCTGRY, OPXP22X)"
    )
    assert _in_scope_cost(con, "outpatient", "OPXP22X") == 125.0
