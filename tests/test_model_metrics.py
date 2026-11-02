"""Tests for the shared M3 metrics (issue #23), on hand-made rows."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import metrics as mm


def test_tweedie_deviance_values_at_power_1_5():
    # worked by hand for mu = 1: y = 4 gives 4, and y = 0 gives 4
    assert mm.tweedie_deviance([4.0], [1.0]) == pytest.approx(4.0)
    assert mm.tweedie_deviance([0.0], [1.0]) == pytest.approx(4.0)
    assert mm.tweedie_deviance([3.0, 7.0], [3.0, 7.0]) == pytest.approx(0.0)


def test_tweedie_deviance_is_smallest_when_the_prediction_is_the_mean():
    y = np.array([0.0, 0.0, 10.0, 30.0])
    grid = np.linspace(2, 20, 181)
    best = grid[np.argmin([mm.tweedie_deviance(y, np.full(4, m)) for m in grid])]
    assert best == pytest.approx(y.mean(), abs=0.1)


def test_tweedie_deviance_rejects_a_bad_power_or_a_non_positive_prediction():
    with pytest.raises(ValueError):
        mm.tweedie_deviance([1.0], [1.0], power=2.0)
    with pytest.raises(ValueError):
        mm.tweedie_deviance([1.0], [0.0])


def test_deviance_by_power_reports_each_power():
    result = mm.deviance_by_power([4.0, 0.0], [2.0, 1.0])
    assert list(result) == [1.3, 1.5, 1.7]
    assert result[1.5] == pytest.approx(mm.tweedie_deviance([4.0, 0.0], [2.0, 1.0], 1.5))


def test_gini_of_a_perfect_ranking_reversed_and_constant_predictions():
    exposure = [1, 1]
    assert mm.gini([0, 100], [1, 2], exposure) == pytest.approx(0.5)  # best possible for two rows
    assert mm.gini([0, 100], [2, 1], exposure) == pytest.approx(-0.5)
    assert mm.gini([0, 100], [5, 5], exposure) == pytest.approx(0.0)


def test_gini_does_not_depend_on_row_order_and_uses_exposure():
    a = mm.gini([0, 50, 100], [1, 2, 3], [1, 1, 1])
    b = mm.gini([100, 0, 50], [3, 1, 2], [1, 1, 1])
    assert a == pytest.approx(b)
    # doubling the exposure of the lowest-risk row changes the curve, so the Gini
    heavier = mm.gini([0, 50, 100], [2, 2, 3], [2, 1, 1])
    assert heavier != pytest.approx(a)


def test_gini_ties_are_grouped_so_ordering_cannot_matter():
    first = mm.gini([0, 100, 0, 100], [1, 1, 2, 2], [1, 1, 1, 1])
    second = mm.gini([100, 0, 100, 0], [1, 1, 2, 2], [1, 1, 1, 1])
    assert first == pytest.approx(second)


def test_lift_table_groups_by_predicted_risk_with_exposure_weights():
    table = mm.lift_table(
        actual=[10, 0, 30, 60], predicted=[10, 20, 30, 40], exposure=[1, 1, 1, 1], n=2
    )
    assert table["person_years"].tolist() == [2, 2]
    assert table["actual"].tolist() == [10, 90]
    assert table["predicted"].tolist() == [30, 70]
    assert table["a_e"].tolist() == pytest.approx([10 / 30, 90 / 70])
    assert table["lift"].tolist() == pytest.approx([(10 / 2) / 25, (90 / 2) / 25])


def test_lift_table_with_a_part_year_row_balances_exposure_not_rows():
    table = mm.lift_table(
        actual=[0, 0, 100], predicted=[1, 4, 20], exposure=[0.5, 0.5, 2.0], n=2
    )  # risk per exposure year: 2, 8, 10
    assert table["exposure"].tolist() == pytest.approx([1.0, 2.0])
    assert table["person_years"].tolist() == [2, 1]


def test_ae_by_predicted_decile_is_the_same_table():
    assert mm.ae_by_predicted_decile is mm.lift_table


def test_double_lift_table_orders_by_the_ratio_of_the_two_predictions():
    table = mm.double_lift_table(
        actual=[10, 20, 30, 40],
        predicted_a=[10, 20, 30, 40],
        predicted_b=[20, 20, 20, 20],
        exposure=[1, 1, 1, 1],
        n=2,
    )  # ratio a/b is 0.5, 1, 1.5, 2
    assert table["actual"].tolist() == [30, 70]
    assert table["a_e_a"].tolist() == pytest.approx([1.0, 1.0])
    assert table["a_e_b"].tolist() == pytest.approx([30 / 40, 70 / 40])


def test_ae_by_factor_gives_actual_expected_and_claimants_for_each_level():
    frame = pd.DataFrame(
        {
            "region": pd.Categorical(["1", "1", "2", None], categories=["1", "2"]),
            "exposure": [1.0, 1.0, 0.5, 1.0],
            "cost": [100.0, 0.0, 50.0, 20.0],
            "claimant": [1, 0, 1, 1],
        }
    )
    table = mm.ae_by_factor(frame, [50.0, 50.0, 25.0, 10.0], ["region"]).set_index("level")
    assert table.loc["1", ["person_years", "claimants", "actual", "expected"]].tolist() == [
        2, 1, 100.0, 100.0,
    ]  # fmt: skip
    assert table.loc["2", "a_e"] == pytest.approx(2.0)
    assert table.loc["missing", "a_e"] == pytest.approx(2.0)


def test_baseline_is_the_train_mean_cost_per_exposure_year_times_exposure():
    train = pd.DataFrame({"cost": [0.0, 100.0], "exposure": [1.0, 0.5]})
    test = pd.DataFrame({"cost": [40.0], "exposure": [1.0]})
    rate = 100.0 / 1.5
    assert mm.baseline_predictions(train, test).tolist() == pytest.approx([rate])
    assert mm.baseline_predictions(train, train).tolist() == pytest.approx([rate, rate / 2])


def test_baseline_scores_have_the_headline_columns_and_a_zero_gini():
    train = pd.DataFrame({"cost": [0.0, 100.0, 20.0], "exposure": [1.0, 0.5, 1.0]})
    test = pd.DataFrame({"cost": [40.0, 0.0], "exposure": [1.0, 1.0]})
    scores = mm.baseline_scores(train, test)
    assert scores["split"].tolist() == ["train", "test"]
    assert set(scores.columns) >= {"tweedie_deviance", "mean_tweedie_deviance", "gini", "a_e"}
    # the baseline ranks every person-year the same, so its Gini is 0
    assert scores["gini"].tolist() == pytest.approx([0.0, 0.0])
    assert scores.loc[0, "a_e"] == pytest.approx(1.0)  # the baseline matches train in total


def test_gini_of_a_constant_risk_prediction_is_zero_with_part_year_exposure():
    # predictions of the form rate x exposure do not always divide back to identical risks
    rng = np.random.default_rng(7)
    exposure = rng.choice([0.1, 0.3, 0.7, 1 / 3, 0.58, 1.0], size=5000)
    actual = rng.gamma(0.5, 400.0, size=5000) * (rng.random(5000) < 0.4)
    for rate in (123.456, 77.7, 1 / 7, 2377.5):
        assert mm.gini(actual, rate * exposure, exposure) == pytest.approx(0.0, abs=1e-12)


def test_risks_that_differ_only_by_float_noise_are_tied_but_real_differences_are_not():
    tied = pd.Series([1.0, 1.0 + 1e-13, 2.0])
    assert mm._tie_ids(tied).tolist() == [1, 1, 2]
    assert mm._tie_ids(pd.Series([1.0, 1.0 + 1e-6])).tolist() == [1, 2]


def test_lift_groups_are_by_predicted_risk_per_exposure_not_raw_predicted_cost():
    # row A: cost 30 over one year, risk 30. Row B: cost 20 over half a year, risk 40.
    table = mm.lift_table(actual=[5, 99], predicted=[30, 20], exposure=[1.0, 0.5], n=2)
    assert table["actual"].tolist() == [5, 99]  # group 1 is row A, which has the lower risk
