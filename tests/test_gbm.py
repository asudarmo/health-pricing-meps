"""Tests for the LightGBM challenger and its surrogate tariff (M4-lite)."""

import duckdb
import numpy as np
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import gbm, outofsample


def test_the_grid_has_at_most_twelve_combinations_and_covers_every_value():
    combos = gbm.combinations()
    assert len(combos) == 12
    assert {c["num_leaves"] for c in combos} == {4, 8, 16}
    assert len({tuple(c.values()) for c in combos}) == 12


def test_parameters_use_the_tweedie_objective_and_constrain_only_adult_age():
    params = gbm.parameters(0.05, 8, 100)
    assert params["objective"] == "tweedie" and params["tweedie_variance_power"] == 1.5
    constraints = dict(zip(gbm.FEATURES, params["monotone_constraints"], strict=True))
    assert constraints[gbm.ADULT_AGE] == 1
    assert sum(abs(v) for v in constraints.values()) == 1
    assert params["seed"] == gbm.SEED and params["deterministic"]


def test_survival_is_the_share_of_the_gbm_advantage_that_the_surrogate_keeps():
    table = pd.DataFrame(
        {
            "candidate": [
                gbm.NAMES["gbm"],
                gbm.NAMES["gbm_tariff"],
                gbm.NAMES["glm_tariff"],
            ],
            "gini": [0.40, 0.38, 0.36],
        }
    )
    out = gbm.survival(table)
    assert out["gbm_advantage"] == pytest.approx(0.04)
    assert out["share_kept"] == pytest.approx(0.5)
    deviance = pd.DataFrame(
        {
            "candidate": table["candidate"],
            "tweedie_deviance": [900.0, 910.0, 920.0],
        }
    )
    worse = gbm.survival(deviance, "tweedie_deviance")
    assert worse["gbm_advantage"] == pytest.approx(20.0)
    assert worse["share_kept"] == pytest.approx(0.5)
    none = gbm.survival(table.assign(gini=[0.30, 0.38, 0.36]))
    assert none["gbm_advantage"] < 0 and np.isnan(none["share_kept"])


def test_deviance_gaps_are_reproducible_and_signed():
    rng = np.random.default_rng(1)
    n = 600
    frame = pd.DataFrame(
        {
            "DUID": rng.integers(0, 150, n),
            "cost": rng.gamma(2.0, 500.0, n) * rng.binomial(1, 0.5, n),
        }
    )
    good = np.full(n, frame["cost"].mean())
    bad = good * 3
    predicted = {"good": good, "bad": bad}
    first = gbm.deviance_gaps(frame, predicted, [("bad", "good")], n_boot=200)
    again = gbm.deviance_gaps(frame, predicted, [("bad", "good")], n_boot=200)
    assert first.equals(again)
    row = first.iloc[0]
    assert row["deviance_gap"] > 0 and row["interval_excludes_0"]
    assert row["lower_95"] < row["deviance_gap"] < row["upper_95"]


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
    train = frozen.final_tariff.frames["spline"].train
    grid = {"learning_rate": [0.1], "num_leaves": [4], "min_data_in_leaf": [150]}
    table = gbm.tune(train, grid, n_folds=3)
    fitted = gbm.fit(train, table)
    return frozen, train, table, fitted


def test_folds_never_split_a_household(setup):
    _, train, _, _ = setup
    for fit_index, valid_index in gbm.fold_indices(train, 5):
        fit_households = set(train["DUID"].iloc[fit_index])
        assert not fit_households & set(train["DUID"].iloc[valid_index])


def test_the_fit_is_reproducible_balanced_and_priced_at_the_reference_control(setup):
    frozen, train, table, fitted = setup
    again = gbm.fit(train, table)
    assert np.allclose(fitted.predict(train), again.predict(train))
    assert fitted.predict(train).sum() == pytest.approx(train["cost"].sum())
    other = train.copy()
    codes = other["inscov"].cat.categories
    other["inscov"] = pd.Categorical([codes[-1]] * len(other), categories=codes)
    assert np.allclose(fitted.predict(other), fitted.predict(train))
    assert table["chosen"].sum() == 1


def test_predicted_cost_never_falls_with_adult_age_and_is_proportional_to_exposure(setup):
    _, train, _, fitted = setup
    adults = train[train["age_group3"].astype(str) == "adult"].head(200).copy()
    adults["exposure"] = 1.0
    previous = None
    for age in range(18, 86, 3):
        shifted = adults.copy()
        shifted["age_spline_1"] = float(age)
        values = fitted.predict(shifted)
        if previous is not None:
            assert (values >= previous - 1e-9).all()
        previous = values
    half = adults.assign(exposure=0.5)
    assert np.allclose(fitted.predict(half), 0.5 * fitted.predict(adults))


def test_the_surrogate_tariff_keeps_the_train_total_and_scores_run(setup):
    frozen, train, _, fitted = setup
    tariff, balanced = gbm.surrogate_tariff(fitted, train, frozen.prepared)
    assert tariff.predict(frozen.prepared.train).sum() == pytest.approx(balanced.sum(), rel=1e-6)
    predicted = gbm.predictions(frozen, fitted, tariff, "test")
    table = gbm.scores(frozen, predicted)
    assert set(table["candidate"]) == {gbm.BASELINE, *gbm.NAMES.values()}
    assert table.loc[table["candidate"] == gbm.BASELINE, "gini"].iloc[0] == 0
    assert (table["reduction_pct_dev"].iloc[1:] > 0).all()


def test_the_unconstrained_refit_keeps_the_tuned_values_and_drops_only_the_constraint(setup):
    _, train, _, fitted = setup
    free = gbm.fit_unconstrained(train, fitted)
    assert free.trees == fitted.trees and free.chosen == fitted.chosen
    assert free.predict(train).sum() == pytest.approx(train["cost"].sum())
    assert sum(gbm.parameters(**fitted.chosen, monotone=False)["monotone_constraints"]) == 0
    adults = train[train["age_group3"].astype(str) == "adult"].head(300)
    profile = gbm.age_profile(fitted, adults, range(60, 90, 5))
    assert profile.loc[profile["age"] == 65, "ratio_to_67"].iloc[0] <= 1.0 + 1e-9
    assert (profile["ratio_to_67"].diff().dropna() >= -1e-9).all()
