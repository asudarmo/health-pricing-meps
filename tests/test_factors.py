"""Tests for the permitted factors and factor selection (issue #39)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import factors, glm
from health_pricing.models import frame as mf


def toy(n=3000, seed=21) -> pd.DataFrame:
    """`age` drives claims, `noise` does not, and `ctrl` is a control that raises cost."""
    rng = np.random.default_rng(seed)
    age = rng.choice(["18-24", "25-29", "30-34"], n)
    noise = rng.choice(["r", "u", "v"], n)
    ctrl = rng.choice(["r", "z"], n)
    exposure = rng.uniform(0.3, 1.0, n)
    rate = 0.2 * np.select([age == "25-29", age == "30-34"], [2.0, 4.0], 1.0)
    rate = rate * np.where(ctrl == "z", 1.8, 1.0)
    claimed = rng.random(n) < 1 - np.exp(-rate * exposure)
    cost = np.where(claimed, rng.gamma(2.0, 800.0 * np.where(age == "30-34", 2.0, 1.0)), 0.0)
    return pd.DataFrame(
        {
            "age": pd.Categorical(age, categories=["18-24", "25-29", "30-34"]),
            "noise": pd.Categorical(noise, categories=["r", "u", "v"]),
            "ctrl": pd.Categorical(ctrl, categories=["r", "z"]),
            "exposure": exposure,
            "capped_cost": cost,
        }
    )


def test_options_split_the_factors_as_agreed():
    assert set(factors.ANALYSIS_ONLY) == {"rthlth", "mnhlth", "PHYEXE53", "inscov"}
    one, two = factors.OPTIONS["option_1"], factors.OPTIONS["option_2"]
    assert set(one) == {"age", "region", "OFTSMK53", *factors.CONDITION_FLAGS}
    assert set(two) == {"age", "region", "OFTSMK53"}
    assert set(factors.controls_for("option_1")) == set(factors.ANALYSIS_ONLY)
    assert set(factors.controls_for("option_2")) == set(factors.ANALYSIS_ONLY) | set(
        factors.CONDITION_FLAGS
    )
    assert factors.controls_for("all_factors") == []
    for name, rating in factors.OPTIONS.items():
        covered = set(rating) | set(factors.controls_for(name))
        if name == "final":  # the factors dropped by the rule are in neither list
            assert covered == set(mf.FACTORS) - set(factors.DROPPED_BY_RULE)
        else:
            assert covered == set(mf.FACTORS)
    assert not {"sex", "race", "income", "education"} & set(mf.FACTORS)


def test_a_control_is_set_to_its_reference_and_nothing_else_changes():
    frame = toy(50)
    out = factors.at_reference(frame, ["ctrl"])
    assert (out["ctrl"] == "r").all() and out["ctrl"].cat.categories.tolist() == ["r", "z"]
    assert out["age"].equals(frame["age"]) and (frame["ctrl"] == "z").any()  # input unchanged


def test_a_control_adjusts_the_fit_but_is_not_priced():
    frame = toy()
    model = factors.fit_option(frame, ["age"], ["ctrl"])
    assert model.frequency.params["ctrl=z"] > 0  # the control is in the fit
    twin = frame.iloc[[0, 0]].copy()
    twin["ctrl"] = pd.Categorical(["r", "z"], categories=["r", "z"])
    price = factors.predict_option(model, twin, ["ctrl"])
    assert price[0] == price[1]
    # priced as a rating factor, the same two rows would differ
    assert model.predict(twin)[0] != model.predict(twin)[1]


def test_the_control_changes_the_other_relativities_in_the_fit_only():
    frame = toy()
    with_control = factors.fit_option(frame, ["age"], ["ctrl"])
    without = factors.fit_option(frame, ["age"], [])
    assert "ctrl=z" in with_control.frequency.params and "ctrl=z" not in without.frequency.params


def test_drop_one_tests_find_the_real_factor_and_not_the_noise():
    frame = toy()
    table = factors.drop_one_tests(frame, ["age", "noise"], []).set_index("factor")
    assert table.loc["age", "p_value"] < 1e-6 and table.loc["age", "keep_by_aic"]
    assert table.loc["noise", "p_value"] > 0.01 and not table.loc["noise", "keep_by_aic"]
    assert table.loc["age", "levels_dropped"] == 4  # 2 levels in each of the two parts
    assert table.loc["noise", "levels_dropped"] == 4


def test_drop_one_statistic_matches_a_hand_calculation():
    frame = toy()
    full = factors.fit_option(frame, ["age", "noise"], [])
    reduced = factors.fit_option(frame, ["age"], [])
    expected = (reduced.frequency.deviance - full.frequency.deviance) / full.frequency.scale + (
        reduced.severity.deviance - full.severity.deviance
    ) / full.severity.scale
    aic = expected - 2 * 4  # four extra coefficients, two in each part
    row = factors.drop_one_tests(frame, ["age", "noise"], []).set_index("factor").loc["noise"]
    assert row["lr_statistic"] == pytest.approx(expected)
    assert row["aic_change_if_dropped"] == pytest.approx(aic)


def test_exercise_table_leaves_out_children_and_adjusted_effect_has_intervals():
    frame = toy()
    frame["PHYEXE53"] = pd.Categorical(
        np.where(np.arange(len(frame)) % 3 == 0, "0", "1"), categories=["1", "0"]
    )
    frame["age"] = frame["age"].cat.rename_categories({"18-24": "05-14"})  # make one band children
    table = factors.exercise_table(frame)
    assert table["person_years"].sum() == (frame["age"] != "05-14").sum()
    assert table["claimant_rate"].between(0, 1).all()
    model = glm.fit_two_part(frame, "cloglog", ["age", "PHYEXE53"])
    effect = factors.adjusted_effect(model, frame, "PHYEXE53")
    assert effect["level"].tolist() == ["0"]
    row = effect.iloc[0]
    assert row["frequency_lower_95"] < row["frequency_relativity"] < row["frequency_upper_95"]
    assert row["severity_lower_95"] < row["severity_relativity"] < row["severity_upper_95"]


def test_save_table_writes_the_aggregate(tmp_path):
    table = pd.DataFrame({"factor": ["age"], "p_value": [0.5]})
    path = factors.save_table(table, "x.csv", tmp_path / "sub")
    assert pd.read_csv(path).equals(table)


def _built() -> bool:
    import duckdb

    from health_pricing.data.load import DUCKDB_PATH

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


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_real_all_factor_option_matches_candidate_a_and_controls_are_not_priced():
    prepared = glm.prepare_frames(mf.load_frames())
    results = factors.option_results(prepared)
    candidates = {name: r.candidate for name, r in results.items()}
    model = glm.fit_two_part(prepared.train, "cloglog")
    balance = results["all_factors"].rebalance_factor
    assert candidates["all_factors"].test == pytest.approx(model.predict(prepared.test) * balance)
    assert 0.9 < balance < 1.1  # the full model is already close to balanced on train
    selected = factors.select_by_rule(
        factors.drop_one_tests(
            prepared.train, factors.OPTIONS["option_1"], factors.controls_for("option_1")
        )
    )
    assert selected == factors.FINAL_RATING  # the rule gives the approved ten factors
    # an option-2 prediction ignores a control, so rows that differ only in a flag agree
    controls = factors.controls_for("option_2")
    model_2 = factors.fit_option(prepared.train, factors.OPTIONS["option_2"], controls)
    row = prepared.test.iloc[[0, 0]].copy()
    flag = row["HIBPDX"].cat.categories
    row["HIBPDX"] = pd.Categorical([flag[0], flag[1]], categories=list(flag))
    price = factors.predict_option(model_2, row, controls)
    assert price[0] == price[1]


def test_rebalancing_makes_train_predicted_cost_equal_actual():
    frame = toy().assign(cost=lambda d: d["capped_cost"])
    predicted = np.full(len(frame), 3.0)
    scale = factors.rebalance_factor(frame, predicted)
    assert (predicted * scale).sum() == pytest.approx(frame["cost"].sum())


def test_a_scored_option_is_rebalanced_and_keeps_its_factor_count():
    frame = toy().assign(cost=lambda d: d["capped_cost"])
    prepared = mf.Frames(frame, toy(seed=22).assign(cost=lambda d: d["capped_cost"]), {})
    result = factors.scored_option(prepared, "t", ["age"], ["ctrl"])
    assert result.rating_factors == 1
    assert result.candidate.train.sum() == pytest.approx(frame["cost"].sum())
    model = factors.fit_option(frame, ["age"], ["ctrl"])
    raw_test = factors.predict_option(model, prepared.test, ["ctrl"])
    assert result.candidate.test == pytest.approx(raw_test * result.rebalance_factor)
    assert result.rebalance_factor == pytest.approx(
        frame["cost"].sum() / factors.predict_option(model, frame, ["ctrl"]).sum()
    )
    scores = factors.option_scores(prepared, {"t": result})
    assert set(scores["split"]) == {"train", "test"}
    assert (scores["rating_factors"] == 1).all()
    assert scores.loc[scores["split"] == "train", "a_e"].iloc[0] == pytest.approx(1.0)


def test_select_by_aic_keeps_only_supported_factors():
    tests = pd.DataFrame({"factor": ["a", "b", "c"], "keep_by_aic": [True, False, True]})
    assert factors.select_by_aic(tests) == ["a", "c"]


def test_the_final_set_is_option_1_without_the_four_dropped_factors():
    assert set(factors.DROPPED_BY_RULE) == {"ANGIDX", "MIDX", "STRKDX", "DIABDX_M18"}
    assert len(factors.FINAL_RATING) == 10
    assert set(factors.FINAL_RATING) == {
        "age", "region", "OFTSMK53", "HIBPDX", "CHDDX", "OHRTDX", "CHOLDX", "CANCERDX",
        "ARTHDX", "ASTHDX",
    }  # fmt: skip
    assert set(factors.controls_for("final")) == set(factors.ANALYSIS_ONLY)


def test_the_selection_rule_needs_both_the_p_value_and_aic():
    tests = pd.DataFrame(
        {
            "factor": ["both", "p_only", "aic_only", "neither"],
            "p_value": [0.01, 0.01, 0.09, 0.5],
            "keep_by_aic": [True, False, True, False],
        }
    )
    assert factors.select_by_rule(tests) == ["both"]
    assert factors.select_by_rule(tests, p_value=0.1) == ["both", "aic_only"]


def test_add_back_sensitivity_reports_the_relativity_and_the_deviance_change():
    frame = toy().assign(cost=lambda d: d["capped_cost"])
    prepared = mf.Frames(frame, toy(seed=22).assign(cost=lambda d: d["capped_cost"]), {})
    out = factors.add_back_sensitivity(prepared, "noise", ["age"], ["ctrl"])
    assert out["level"].tolist() == ["u", "v"]
    assert (out["frequency_relativity"] > 0).all() and (out["severity_relativity"] > 0).all()
    gap = out["test_deviance_with"] - out["test_deviance_without"]
    assert out["change_in_test_deviance"].tolist() == pytest.approx(gap.tolist())


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_real_final_model_excludes_the_dropped_factors_and_prices_the_four_controls_at_reference():
    prepared = glm.prepare_frames(mf.load_frames())
    controls = factors.controls_for("final")
    model = factors.fit_option(prepared.train, factors.FINAL_RATING, controls)
    for dropped in factors.DROPPED_BY_RULE:
        assert dropped not in model.factors
        assert not any(term.startswith(f"{dropped}=") for term in model.frequency.params.index)
    assert set(model.factors) == set(factors.FINAL_RATING) | set(factors.ANALYSIS_ONLY)
    sample = prepared.test.iloc[::37].copy()
    base = factors.predict_option(model, sample, controls)
    for control in factors.ANALYSIS_ONLY:
        changed = sample.copy()
        categories = list(changed[control].cat.categories)
        changed[control] = pd.Categorical([categories[-1]] * len(changed), categories=categories)
        assert factors.predict_option(model, changed, controls) == pytest.approx(base)
