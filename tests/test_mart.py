"""Tests for the modelling table mart_person_year (issue #17)."""

from pathlib import Path

import duckdb
import pytest
import yaml

from health_pricing.data.load import DUCKDB_PATH

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "dbt" / "models" / "marts" / "schema.yml"

# Persons with a positive weight, from AHRQ's documentation (2023) and the HC-243 file (2022).
EXPECTED_ROWS = {2022: 21_747, 2023: 18_463}

# Allowed rating factor candidates. Sex, the leaver flag, race, income and education are not.
RATING_FACTORS = {
    "age", "region", "inscov", "rthlth", "mnhlth", "OFTSMK53", "PHYEXE53", "HIBPDX", "CHDDX",
    "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX", "CANCERDX", "ARTHDX", "ASTHDX", "DIABDX_M18",
}  # fmt: skip
NEVER_RATING_FACTORS = {"SEX", "left_survey_early", "age_source", "region_source", "age_topcoded"}
BANNED_NAME_PARTS = ("RACE", "POVCAT", "POVLEV", "INCOME", "FAMINC", "EDUC", "HIDEG", "EDUCYR")


def _roles():
    model = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))["models"][0]
    return {c["name"]: c["meta"]["role"] for c in model["columns"]}


def test_every_column_has_a_role_and_rating_factors_are_the_allowed_list():
    roles = _roles()
    rating = {name for name, role in roles.items() if role == "rating_factor"}
    assert rating == RATING_FACTORS
    assert set(roles.values()) <= {
        "key", "rating_factor", "analysis_only", "exposure", "claim", "weight"
    }  # fmt: skip


def test_sex_and_the_leaver_flag_are_analysis_only_never_rating_factors():
    roles = _roles()
    for name in NEVER_RATING_FACTORS:
        assert roles[name] == "analysis_only", name
    assert not (set(roles) & NEVER_RATING_FACTORS & RATING_FACTORS)


def test_no_race_income_or_education_column_is_declared():
    for name in _roles():
        assert not any(part in name.upper() for part in BANNED_NAME_PARTS), name


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'mart_person_year'"
        ).fetchone()
        return row[0] == 1
    finally:
        con.close()


built = pytest.mark.skipif(not _built(), reason="run the load script and dbt build")


@built
def test_built_columns_match_the_declared_columns_and_exclude_banned_names():
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        built_columns = [r[0] for r in con.execute("DESCRIBE mart_person_year").fetchall()]
    finally:
        con.close()
    assert set(built_columns) == set(_roles())
    for name in built_columns:
        assert not any(part in name.upper() for part in BANNED_NAME_PARTS), name


@built
@pytest.mark.parametrize("year", [2022, 2023])
def test_row_count_equals_the_modelling_population(year):
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        rows = con.execute(
            "SELECT COUNT(*) FROM mart_person_year WHERE year = ?", [year]
        ).fetchone()
        retained = con.execute(
            "SELECT COUNT(*) FROM int_person_retained WHERE year = ?", [year]
        ).fetchone()
        raw = con.execute(f"SELECT COUNT(*) FROM stg_fyc_{year} WHERE perwt > 0").fetchone()
    finally:
        con.close()
    assert rows[0] == retained[0] == raw[0] == EXPECTED_ROWS[year]


@built
def test_key_is_unique_and_claims_agree_with_the_claims_table():
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        distinct = con.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT DUPERSID, year FROM mart_person_year)"
        ).fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM mart_person_year").fetchone()[0]
        assert distinct == total
        mismatch = con.execute(
            "SELECT COUNT(*) FROM mart_person_year m "
            "JOIN int_person_claims c USING (year, DUPERSID) "
            "WHERE m.claim_count <> c.claim_count OR m.claim_cost <> c.claim_cost "
            "OR m.claim_cost_2023_prices <> c.claim_cost_2023_prices"
        ).fetchone()[0]
        assert mismatch == 0
        # Every rating factor candidate has a value or a documented level for every row, except
        # the health status items that are null when every round was invalid.
        nulls = con.execute(
            "SELECT COUNT(*) FROM mart_person_year WHERE age IS NULL OR region IS NULL "
            "OR inscov IS NULL OR exposure IS NULL OR claim_count IS NULL"
        ).fetchone()[0]
        assert nulls == 0
    finally:
        con.close()
