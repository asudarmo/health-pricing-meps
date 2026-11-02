"""Tests for the large-claim cap evidence (issue #27)."""

import duckdb
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import frame as mf
from health_pricing.models import large_claims as lc

COST = pd.Series([100.0, 200.0, 300.0, 400.0, 1000.0])


def test_percentile_table_runs_to_the_maximum():
    table = lc.percentile_table(COST)
    assert table["percentile"].iloc[0] == "P50" and table["percentile"].iloc[-1] == "Max"
    assert table["cost_per_claimant"].iloc[0] == 300.0
    assert table["cost_per_claimant"].iloc[-1] == 1000.0
    assert table["cost_per_claimant"].is_monotonic_increasing


def test_the_cap_comparison_by_hand():
    table = lc.cap_comparison(COST, {"$500": 500.0, "$150": 150.0}).set_index("cap")
    five = table.loc["$500"]
    assert five["claimants_above"] == 1 and five["share_of_claimants_above"] == 0.2
    assert five["share_of_cost_above_cap"] == pytest.approx(500 / 2000)
    assert five["mean_severity"] == 400.0 and five["mean_severity_capped"] == 300.0
    assert five["change_in_mean_severity"] == pytest.approx(-0.25)
    low = table.loc["$150"]
    # excess is 50 + 150 + 250 + 850 = 1300 of 2000
    assert low["claimants_above"] == 4
    assert low["share_of_cost_above_cap"] == pytest.approx(1300 / 2000)


def test_a_cap_above_the_maximum_changes_nothing():
    row = lc.cap_comparison(COST, {"big": 5000.0}).iloc[0]
    assert row["claimants_above"] == 0 and row["change_in_mean_severity"] == 0


def test_resolved_caps_are_percentiles_of_train_and_sorted():
    cost = pd.Series(range(1, 1001), dtype=float)
    caps = lc.resolve_caps(cost)
    assert list(caps.values()) == sorted(caps.values())
    assert caps["P99"] == pytest.approx(cost.quantile(0.99))
    assert caps["$100,000"] == 100_000.0
    assert len(caps) == len(lc.PERCENTILE_CAPS) + len(lc.FIXED_CAPS)


def test_stability_uses_the_train_cap_on_both_splits():
    test = pd.Series([100.0, 900.0])
    table = lc.stability_table(COST, test, {"$500": 500.0}).iloc[0]
    assert table["train_claimants_above"] == 1 and table["test_claimants_above"] == 1
    assert table["test_share_of_cost_above_cap"] == pytest.approx(400 / 1000)


def test_excess_load_is_excess_over_capped_cost_overall_and_by_segment():
    frame = pd.DataFrame(
        {"cost": [100.0, 1000.0, 200.0, 600.0], "seg": ["a", "a", "b", "b"]},
    )
    overall = lc.excess_load_table(frame, 500.0).iloc[0]
    # capped 100 + 500 + 200 + 500 = 1300, excess 500 + 100 = 600
    assert overall["capped_cost"] == 1300 and overall["excess_cost"] == 600
    assert overall["excess_load"] == pytest.approx(600 / 1300)
    by = lc.excess_load_table(frame, 500.0, "seg").set_index("segment")
    assert by.loc["a", "excess_load"] == pytest.approx(500 / 600)
    assert by.loc["b", "claimants_above"] == 1
    assert by["excess_cost"].sum() == overall["excess_cost"]
    # capped plus excess recovers the uncapped total
    assert overall["capped_cost"] + overall["excess_cost"] == frame["cost"].sum()


def test_age_groups_cover_every_age():
    groups = lc.age_group(pd.Series([0, 17, 18, 39, 40, 64, 65, 85]))
    assert groups.tolist() == ["0-17", "0-17", "18-39", "18-39", "40-64", "40-64", "65+", "65+"]


def test_benefit_comparison_sets_percentile_caps_within_each_type():
    rows = []
    for benefit, scale in (("inpatient_daycase", 10.0), ("outpatient", 1.0)):
        for i in range(1, 201):
            rows.append({"split": "train", "benefit_type": benefit, "age": 40, "cost": i * scale})
    rows.append({"split": "test", "benefit_type": "outpatient", "age": 40, "cost": 1e9})
    table = lc.benefit_cap_comparison(pd.DataFrame(rows))
    p99 = table[table["cap"] == "P99"].set_index("benefit_type")["cap_amount"]
    assert p99["inpatient_daycase"] == pytest.approx(10 * p99["outpatient"])
    assert (table["claimants"] == 200).all()  # test rows are not used


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


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_real_claimants_match_the_frames_and_the_cap_excess_adds_up():
    frames = mf.load_frames()
    claimants = frames.train[frames.train["claimant"] == 1]["cost"]
    benefit = lc.load_benefit_claimants()
    assert set(benefit["split"]) == {"train", "test"}
    caps = lc.resolve_caps(claimants)
    table = lc.cap_comparison(claimants, caps)
    assert table["share_of_cost_above_cap"].is_monotonic_decreasing
    # benefit-type costs add to the person-year cost, so the totals agree
    train_benefit = benefit[benefit["split"] == "train"]["cost"].sum()
    assert train_benefit == pytest.approx(claimants.sum())
