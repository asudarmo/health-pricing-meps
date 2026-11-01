"""Tests for the aggregated tables behind the EDA notebook (issue #21)."""

import duckdb
import pandas as pd
import pytest

from health_pricing import eda

PERSON_LEVEL_COLUMNS = {"DUPERSID", "DUID", "perwt", "VARSTR", "VARPSU"}


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE mart_person_year (DUPERSID VARCHAR, DUID BIGINT, year BIGINT, split VARCHAR, "
        "age BIGINT, SEX BIGINT, region BIGINT, HIBPDX VARCHAR, ASTHDX VARCHAR, exposure DOUBLE, "
        "claim_count BIGINT, claim_cost_2023_prices DOUBLE)"
    )
    rows = [
        ("a", 1, 2022, "train", 10, 1, 1, "not_applicable", "0", 1.0, 0, 0.0),
        ("b", 2, 2022, "train", 30, 2, 2, "0", "1", 1.0, 2, 300.0),
        ("c", 3, 2022, "test", 30, 2, 2, "1", "0", 0.5, 1, 500.0),
        ("d", 4, 2023, "out_of_time", 80, 1, 3, "unknown", "0", 1.0, 3, 1000.0),
    ]
    c.executemany("INSERT INTO mart_person_year VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    for flag in eda.CONDITION_FLAGS:
        if flag not in ("HIBPDX", "ASTHDX"):
            c.execute(f"ALTER TABLE mart_person_year ADD COLUMN {flag} VARCHAR DEFAULT '0'")
    return c


def test_age_band_rates_are_claims_per_exposure_year_and_cost_per_claim(con):
    table = eda.by_age_band(con).set_index("age_band")
    row = table.loc["25-34"]
    assert row["persons"] == 2
    assert row["exposure"] == 1.5
    assert row["frequency"] == pytest.approx(3 / 1.5)
    assert row["severity"] == pytest.approx(800 / 3)
    assert row["pure_premium"] == pytest.approx(800 / 1.5)


def test_a_level_with_no_claims_has_no_severity_not_a_division_error(con):
    row = eda.by_age_band(con).set_index("age_band").loc["00-17"]
    assert row["frequency"] == 0
    assert pd.isna(row["severity"])


def test_sex_and_region_labels(con):
    assert set(eda.by_sex(con)["sex"]) == {"Male", "Female"}
    assert "3 South" in set(eda.by_region(con)["region"])


def test_condition_table_keeps_answered_adult_levels_only(con):
    table = eda.by_condition(con)
    blood_pressure = table[table["condition"] == "HIBPDX"]
    assert set(blood_pressure["level"]) == {"0", "1"}  # not_applicable and unknown are left out
    assert blood_pressure["persons"].sum() == 2  # the adult aged 80 is unknown, the child is n/a


def test_zero_claim_share_by_year(con):
    table = eda.zero_claim_share(con).set_index("year")
    assert table.loc[2022, "zero_claim_share"] == pytest.approx(1 / 3)
    assert table.loc[2023, "zero_claim_share"] == 0


def test_exposure_distribution_is_in_whole_months(con):
    table = eda.exposure_distribution(con).set_index("months")["persons"]
    assert table.loc[12] == 3
    assert table.loc[6] == 1


def test_claim_cost_bins_are_log_scale_and_count_claimants_only(con):
    table = eda.claim_cost_distribution(con).set_index("log10_low")["claimants"]
    assert table.sum() == 3  # the person with no claim is out
    assert table.loc[3.0] == 1  # 1,000 is 10^3
    assert table.loc[2.25] == 1  # 300 is 10^2.477, in the bin starting 2.25


def test_split_balance_shares_add_to_one_within_each_year(con):
    table = eda.split_balance(con)
    for _, group in table.groupby("year"):
        assert group["persons_share"].sum() == pytest.approx(1)
        assert group["claim_cost_share"].sum() == pytest.approx(1)


def test_no_aggregate_carries_person_level_columns(con):
    tables = [
        eda.by_age_band(con), eda.by_sex(con), eda.by_region(con), eda.by_condition(con),
        eda.exposure_distribution(con), eda.zero_claim_share(con),
        eda.claim_cost_distribution(con), eda.split_balance(con),
    ]  # fmt: skip
    for table in tables:
        assert not (set(table.columns) & PERSON_LEVEL_COLUMNS)
