"""Tests for the forward accuracy of the frozen model on 2023 (M5, issue #44)."""

import duckdb
import numpy as np
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import frame as mf
from health_pricing.models import monitoring, outofsample, trend


def toy(n=900, seed=3, households=200):
    rng = np.random.default_rng(seed)
    labels = pd.Series(rng.choice(["a", "b", "c"], n))
    predicted = rng.uniform(500, 3000, n)
    actual = predicted * rng.gamma(4.0, 0.25, n)
    return rng.integers(0, households, n), labels, actual, predicted


def test_grouped_ae_matches_a_hand_calculation_and_the_relative_ae():
    households, labels, actual, predicted = toy()
    table = monitoring.grouped_ae(households, labels, actual, predicted, n_boot=200)
    for _, row in table.iterrows():
        mask = (labels == row["label"]).to_numpy()
        assert row["a_e"] == pytest.approx(actual[mask].sum() / predicted[mask].sum())
        assert row["actual"] == pytest.approx(actual[mask].sum())
        assert row["lower_95"] < row["a_e"] < row["upper_95"]
    overall = actual.sum() / predicted.sum()
    assert table["relative_a_e"].tolist() == pytest.approx((table["a_e"] / overall).tolist())
    assert (table["relative_lower_95"] < table["relative_upper_95"]).all()


def test_a_uniform_level_shift_does_not_change_the_relative_ae():
    households, labels, actual, predicted = toy()
    base = monitoring.grouped_ae(households, labels, actual, predicted, n_boot=100)
    shifted = monitoring.grouped_ae(households, labels, actual, predicted * 1.2, n_boot=100)
    assert shifted["relative_a_e"].tolist() == pytest.approx(base["relative_a_e"].tolist())
    assert shifted["a_e"].tolist() == pytest.approx((base["a_e"] / 1.2).tolist())
    assert shifted["relative_lower_95"].tolist() == pytest.approx(
        base["relative_lower_95"].tolist()
    )


def test_the_bootstrap_is_reproducible_and_a_single_household_has_no_spread():
    households, labels, actual, predicted = toy()
    first = monitoring.grouped_ae(households, labels, actual, predicted, n_boot=100)
    again = monitoring.grouped_ae(households, labels, actual, predicted, n_boot=100)
    assert first["lower_95"].tolist() == again["lower_95"].tolist()
    single = monitoring.grouped_ae(np.zeros_like(households), labels, actual, predicted, n_boot=50)
    assert single["lower_95"].tolist() == pytest.approx(single["a_e"].tolist())


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


pytestmark_real = pytest.mark.skipif(not _built(), reason="run the load script and dbt build")


@pytest.fixture(scope="module")
def setup():
    if not _built():
        pytest.skip("run the load script and dbt build")
    frozen = outofsample.freeze()
    oot = outofsample.load_out_of_time(frozen)
    predictions = monitoring.forecast(frozen, oot, 1.019)
    return frozen, oot, predictions


@pytestmark_real
def test_the_forecast_multiplies_expected_cost_by_the_factor(setup):
    frozen, oot, predictions = setup
    none = monitoring.forecast(frozen, oot, 1.0)
    for name in predictions:
        assert predictions[name] == pytest.approx(none[name] * 1.019)
    overall = monitoring.overall(oot, predictions, n_boot=200).set_index("model")
    assert overall.loc[outofsample.TECHNICAL, "a_e"] == pytest.approx(1.1454, abs=1e-3)
    assert overall.loc[outofsample.TARIFF, "a_e"] == pytest.approx(1.1454, abs=2e-3)
    assert (overall["lower_95"] < overall["a_e"]).all()


@pytestmark_real
def test_a_e_by_level_covers_every_level_of_every_factor_and_adds_up(setup):
    _, oot, predictions = setup
    table = monitoring.by_level(oot, predictions[outofsample.TARIFF], n_boot=100)
    assert set(table["factor"]) == set(mf.FACTORS)
    for factor, rows in table.groupby("factor"):
        assert rows["person_years"].sum() == len(oot.frame), factor
        assert rows["actual"].sum() == pytest.approx(oot.frame["cost"].sum())
    assert set(table["role"]) == {"rating", "analysis_only", "dropped"}
    assert (table.loc[table["outside_band"], "claimants"] >= monitoring.MIN_CLAIMANTS).all()


@pytestmark_real
def test_flagged_levels_and_the_count_of_levels_outside_the_band(setup):
    _, oot, predictions = setup
    table = monitoring.by_level(oot, predictions[outofsample.TARIFF], n_boot=100)
    checked = table[table["enough_claimants"] & (table["role"] == "rating")]
    assert checked["outside_band"].sum() > 0
    assert (
        checked["moves_with_the_book"]
        == ((checked["relative_lower_95"] <= 1) & (checked["relative_upper_95"] >= 1))
    ).all()
    flagged = monitoring.flagged(table)
    assert flagged["outside_band"].all() and flagged["enough_claimants"].all()
    assert int(checked["outside_band"].sum()) == 15


@pytestmark_real
def test_lift_age_groups_scores_and_double_lift(setup):
    frozen, oot, predictions = setup
    lift = monitoring.lift(oot, predictions, n_groups=(5,), n_boot=100)
    assert set(lift["model"]) == set(predictions) and set(lift["groups"]) == {5}
    assert lift.groupby("model")["person_years"].sum().tolist() == [len(oot.frame)] * 2
    ages = monitoring.by_age_group(oot, predictions, n_boot=100)
    assert set(ages["age_group"]) == set(trend.AGE_GROUPS)
    scores = monitoring.scores(frozen, oot, predictions).set_index("candidate")
    assert scores.loc[monitoring.BASELINE, "gini"] == 0
    assert scores.loc[outofsample.TARIFF, "gini"] > 0.3
    assert scores.loc[outofsample.TECHNICAL, "deviance_reduction_pct"] > 0
    assert {"tweedie_deviance_p1_3", "tweedie_deviance_p1_7"} <= set(scores.columns)
    double = monitoring.double_lift(oot, predictions)
    assert len(double) == 10
    assert double["exposure"].sum() == pytest.approx(oot.frame["exposure"].sum())
