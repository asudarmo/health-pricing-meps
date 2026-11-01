"""Integration test for the raw-to-DuckDB loader.

Needs the actual MEPS raw files (uv run python -m health_pricing.data.download) and the loader
to have run (uv run python -m health_pricing.data.load) at least once. Both are git-ignored, so
this skips rather than fails in CI or on a clean clone that has not pulled the data yet.

The skip check looks for the raw.fyc_2022 table itself, not just the .duckdb file's existence,
because `dbt debug` creates an empty .duckdb file as a side effect of testing the connection,
which would otherwise make these tests appear "built" when no data has actually been loaded.
"""

import duckdb
import pytest

from health_pricing.data.load import DUCKDB_PATH


def _raw_tables_are_loaded() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'raw'"
        ).fetchone()
        return row[0] > 0
    finally:
        connection.close()


pytestmark = pytest.mark.skipif(
    not _raw_tables_are_loaded(),
    reason="data/interim/meps.duckdb has no raw tables, run the download and load scripts",
)

# Person counts AHRQ documents for the Full-Year Consolidated files (AGENTS.md, _docs/plan.md).
EXPECTED_PERSON_COUNTS = {"fyc_2022": 22_431, "fyc_2023": 18_919}
EXPECTED_POSITIVE_WEIGHT_COUNTS = {"fyc_2022": 21_747, "fyc_2023": 18_463}

# Event record counts AHRQ documents on each file's own doc.shtml page (fetched directly,
# quoted word for word there, e.g. h248gdoc.shtml: "This OB PUF contains 135,096 office-based
# provider event records").
EXPECTED_EVENT_COUNTS = {
    "office_based_2022": 151_263,
    "office_based_2023": 135_096,
    "outpatient_2022": 23_349,
    "outpatient_2023": 20_720,
    "inpatient_2022": 1_933,
    "inpatient_2023": 1_830,
}


@pytest.fixture
def con():
    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.parametrize("table,expected", EXPECTED_PERSON_COUNTS.items())
def test_person_count_matches_ahrq_documentation(con, table, expected):
    actual = con.execute(f"SELECT COUNT(*) FROM raw.{table}").fetchone()[0]
    assert actual == expected


def test_2023_positive_weight_count_matches_ahrq_documentation(con):
    actual = con.execute("SELECT COUNT(*) FROM raw.fyc_2023 WHERE PERWT23F > 0").fetchone()[0]
    assert actual == EXPECTED_POSITIVE_WEIGHT_COUNTS["fyc_2023"]


def test_2022_positive_weight_count_matches_ahrq_documentation(con):
    actual = con.execute("SELECT COUNT(*) FROM raw.fyc_2022 WHERE PERWT22F > 0").fetchone()[0]
    assert actual == EXPECTED_POSITIVE_WEIGHT_COUNTS["fyc_2022"]


@pytest.mark.parametrize("table,expected", EXPECTED_EVENT_COUNTS.items())
def test_event_file_count_matches_ahrq_documentation(con, table, expected):
    actual = con.execute(f"SELECT COUNT(*) FROM raw.{table}").fetchone()[0]
    assert actual == expected


# Regression test for the M1 loader bug found in M2 (#8). AHRQ stores event costs and weights
# with literal decimal points, and an extra division by 10^decimals made them 100x and 10^6x too
# small. Event-file totals must agree with the FYC service-category totals, and the weights must
# sum to the US civilian non-institutionalised population (about 330 million).
@pytest.mark.parametrize(
    ("year", "suffix"),
    [(2022, "22"), (2023, "23")],
)
def test_event_cost_and_weight_scale(year, suffix):
    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        pairs = [
            (f"office_based_{year}", f"OBXP{suffix}X", f"OBVEXP{suffix}"),
            (f"outpatient_{year}", f"OPXP{suffix}X", f"OPTEXP{suffix}"),
            (f"inpatient_{year}", f"IPXP{suffix}X", f"IPTEXP{suffix}"),
        ]
        for table, event_col, fyc_col in pairs:
            events = connection.execute(f"SELECT SUM({event_col}) FROM raw.{table}").fetchone()[0]
            fyc = connection.execute(f"SELECT SUM({fyc_col}) FROM raw.fyc_{year}").fetchone()[0]
            assert events == pytest.approx(fyc, rel=0.001), table
        weight_total = connection.execute(
            f"SELECT SUM(PERWT{suffix}F) FROM raw.fyc_{year}"
        ).fetchone()[0]
        assert 300e6 < weight_total < 350e6
    finally:
        connection.close()
