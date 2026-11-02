"""Tests for the trend sensitivity (M5, issue #48)."""

import duckdb
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import outofsample, sensitivity
from health_pricing.models import recalibration as rule


def test_scenario_factors_are_the_quartiles_and_the_median():
    row = {"p25": 1.008, "p50": 1.019, "p75": 1.031}
    assert sensitivity.scenario_factors(row) == {"Low": 1.008, "Central": 1.019, "High": 1.031}


def _evidence():
    return rule.Evidence(
        a_e=1.145,
        a_e_lower=1.075,
        a_e_upper=1.22,
        claimants=8000,
        severity_cv2=5.4,
        frequency_p=0.6,
        severity_p=0.3,
        levels_beyond_noise=1,
        levels_compared=13,
        off_book_levels=2,
        off_book_checked=34,
        max_psi=0.002,
        gini_later=0.47,
        gini_earlier=0.39,
    )


def _overall(scenarios, trends, a_e, lower, upper):
    return pd.DataFrame(
        {
            "model": "m",
            "scenario": scenarios,
            "trend": trends,
            "a_e": a_e,
            "lower_95": lower,
            "upper_95": upper,
        }
    )


def test_conclusions_apply_the_rule_to_each_trend_and_the_total_move_is_trend_times_rebase():
    overall = _overall(["Low", "High"], [1.008, 1.031], [1.158, 1.132], [1.09, 1.06], [1.23, 1.20])
    table = sensitivity.conclusions(_evidence(), overall, "m")
    assert table["action"].tolist() == [rule.REBASE, rule.REBASE]
    assert sensitivity.same_action(table)
    full = table["total_move_sampling_weight"]
    assert full.iloc[0] == pytest.approx(1.008 * 1.158)
    assert full.iloc[1] == pytest.approx(1.031 * 1.132)
    assert (table["total_move_persistence_weight"] < full).all()


def test_the_action_changes_when_a_trend_removes_the_gap():
    overall = _overall(["High"], [1.2], [0.99], [0.92], [1.07])
    table = sensitivity.conclusions(_evidence(), overall, "m")
    assert table["action"].tolist() == [rule.DO_NOTHING]


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        query = (
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'mart_person_year'"
        )
        return con.execute(query).fetchone()[0] == 1
    finally:
        con.close()


@pytest.fixture(scope="module")
def setup():
    if not _built():
        pytest.skip("run the load script and dbt build")
    frozen = outofsample.freeze()
    return frozen, outofsample.load_out_of_time(frozen)


def test_a_trend_changes_no_relativity_and_the_a_e_moves_with_it(setup):
    frozen, oot = setup
    factors = {"Low": 1.008, "Central": 1.019, "High": 1.031}
    effect = sensitivity.relativity_effect(frozen, oot, factors)
    assert (effect["spread_of_ratio_over_rows"] < 1e-9).all()
    overall, ages = sensitivity.trend_sensitivity(frozen, oot, factors, n_boot=100)
    technical = overall[overall["model"] == outofsample.TECHNICAL].set_index("scenario")["a_e"]
    assert technical["Low"] > technical["Central"] > technical["High"]
    assert technical["Central"] == pytest.approx(1.1453, abs=1e-3)
    assert len(ages) == 3 * 2 * 4
