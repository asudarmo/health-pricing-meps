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
