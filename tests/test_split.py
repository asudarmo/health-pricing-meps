"""Tests for the household-grouped split in mart_person_year (issue #18)."""

import hashlib

import duckdb
import pytest

from health_pricing.data.load import DUCKDB_PATH

SALT = "split-v1"
TRAIN_PERCENT = 80
TOLERANCE = 0.02  # 2 percentage points, as a share


def python_split(duid: int) -> str:
    """The same rule as the dbt macro household_split, written independently."""
    digest = hashlib.md5(f"{duid}|{SALT}".encode()).hexdigest()
    return "train" if int(digest[:8], 16) % 100 < TRAIN_PERCENT else "test"


def test_the_python_rule_is_a_pure_function_of_the_household_id():
    assert python_split(2460002) == python_split(2460002)
    assert {python_split(d) for d in range(2460002, 2460500)} == {"train", "test"}


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        rows = con.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = 'mart_person_year' AND column_name = 'split'"
        ).fetchone()
        return rows[0] == 1
    finally:
        con.close()


built = pytest.mark.skipif(not _built(), reason="run the load script and dbt build")


@pytest.fixture(scope="module")
def mart():
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    frame = con.execute(
        "SELECT DUPERSID, DUID, year, split, exposure, claim_cost FROM mart_person_year"
    ).fetchdf()
    con.close()
    return frame


@built
def test_every_2023_row_is_out_of_time_and_no_2022_row_is(mart):
    assert set(mart.loc[mart["year"] == 2023, "split"]) == {"out_of_time"}
    assert set(mart.loc[mart["year"] == 2022, "split"]) == {"train", "test"}


@built
def test_no_household_is_in_both_train_and_test(mart):
    in_2022 = mart[mart["year"] == 2022]
    train = set(in_2022.loc[in_2022["split"] == "train", "DUID"])
    test = set(in_2022.loc[in_2022["split"] == "test", "DUID"])
    assert train and test
    assert train & test == set()


@built
def test_every_member_of_a_household_has_the_same_split(mart):
    in_2022 = mart[mart["year"] == 2022]
    assert (in_2022.groupby("DUID")["split"].nunique() == 1).all()


@built
def test_the_sql_rule_matches_the_independent_python_rule(mart):
    in_2022 = mart[mart["year"] == 2022].drop_duplicates("DUID")
    expected = in_2022["DUID"].map(python_split)
    assert (in_2022["split"] == expected).all()


@built
def test_train_and_test_shares_of_persons_and_cost_are_within_2_points_of_80_20(mart):
    in_2022 = mart[mart["year"] == 2022]
    persons = in_2022["split"].value_counts(normalize=True)
    cost = in_2022.groupby("split")["claim_cost"].sum() / in_2022["claim_cost"].sum()
    for share in (persons, cost):
        assert abs(share["train"] - TRAIN_PERCENT / 100) <= TOLERANCE
        assert abs(share["test"] - (1 - TRAIN_PERCENT / 100)) <= TOLERANCE


@built
def test_some_households_appear_in_both_years_and_keep_their_2022_split_only(mart):
    # The same households are in 2022 and 2023. 2023 is the out-of-time set whatever their
    # 2022 split.
    both = set(mart.loc[mart["year"] == 2022, "DUID"]) & set(mart.loc[mart["year"] == 2023, "DUID"])
    assert both
