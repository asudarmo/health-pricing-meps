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
        "('A', 1, 1000.0), ('B', 4, 500.0), ('C', -8, 200.0)) t(DUPERSID, RSNINHOS, IPXP22X)"
    )
    return c


def _in_scope_cost(con, event_type, cost_col):
    return con.execute(
        f"SELECT COALESCE(SUM({cost_col}), 0) FROM raw.{event_type}_2022 "
        f"WHERE {pmi_scope.in_scope_condition(event_type)}"
    ).fetchone()[0]


def test_office_based_rules(con):
    assert _in_scope_cost(con, "office_based", "OBXP22X") == 130.0


def test_inpatient_excludes_birth_but_keeps_unknown_reason(con):
    assert _in_scope_cost(con, "inpatient", "IPXP22X") == 1200.0


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
