"""Tests for the year-neutral FYC staging models (issue #9).

Needs the raw tables loaded and `dbt build` run. Skips otherwise, like tests/test_load.py.
"""

import duckdb
import pytest

from health_pricing.data.load import DUCKDB_PATH


def _staging_is_built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name IN ('stg_fyc_2022', 'stg_fyc_2023')"
        ).fetchone()
        return row[0] == 2
    finally:
        con.close()


pytestmark = pytest.mark.skipif(
    not _staging_is_built(), reason="run the load script and dbt build first"
)

# The shortlist from _docs/variable-mapping.md, in the year-neutral names.
EXPECTED_COLUMNS = {
    "year", "AGELAST", "DUID", "PID", "DUPERSID", "PANEL", "VARSTR", "VARPSU", "famid", "perwt",
    "age", "SEX",
    "region", "inscov", "ENDRFM", "ENDRFY", "ELGRND", "OFTSMK53", "PHYEXE53", "HIBPDX", "CHDDX",
    "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX", "CANCERDX", "ARTHDX", "ASTHDX", "ASSTIL31",
    "DIABDX_M18", "OBTOTV", "OPTOTV", "ERTOT", "IPDIS", "IPNGTD", "RXTOT", "OBDRV", "TOTEXP",
    "TOTSLF", "TOTMCR", "TOTMCD", "TOTPRV", "TOTPTR", "OBVEXP", "OBDEXP", "OPTEXP", "ERTEXP",
    "IPTEXP", "RXEXP",
}  # fmt: skip
ROUND_STEMS = ("RTHLTH", "MNHLTH", "BEGRFM", "BEGRFY", "ENDRFM", "ENDRFY", "ELGRND")
EXPECTED_COLUMNS |= {f"{stem}{rnd}" for stem in ROUND_STEMS for rnd in (31, 42, 53)}

# Person counts AHRQ documents for the two files (see tests/test_load.py).
EXPECTED_ROWS = {2022: 22_431, 2023: 18_919}


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    yield c
    c.close()


def _describe(con, year):
    return [(r[0].upper(), r[1]) for r in con.execute(f"DESCRIBE stg_fyc_{year}").fetchall()]


def test_both_years_have_the_same_column_names_and_types(con):
    assert _describe(con, 2022) == _describe(con, 2023)


def test_columns_are_exactly_the_shortlist(con):
    names = {name for name, _ in _describe(con, 2022)}
    assert names == {c.upper() for c in EXPECTED_COLUMNS}


def test_year_suffixed_names_are_gone(con):
    names = {name for name, _ in _describe(con, 2023)}
    assert not {n for n in names if n.endswith(("22", "23")) or n.endswith(("22X", "23X"))}


@pytest.mark.parametrize("year", [2022, 2023])
def test_row_count_and_year_value(con, year):
    rows, years = con.execute(f"SELECT COUNT(*), MIN(year) FROM stg_fyc_{year}").fetchone()
    assert rows == EXPECTED_ROWS[year]
    assert years == year
    assert con.execute(f"SELECT MAX(year) FROM stg_fyc_{year}").fetchone()[0] == year


def test_values_are_unchanged_from_raw(con):
    raw = con.execute(
        "SELECT SUM(AGE23X), SUM(TOTEXP23), SUM(PERWT23F) FROM raw.fyc_2023"
    ).fetchone()
    stg = con.execute("SELECT SUM(age), SUM(TOTEXP), SUM(perwt) FROM stg_fyc_2023").fetchone()
    assert raw == stg
