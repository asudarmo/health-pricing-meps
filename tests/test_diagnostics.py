"""Tests for the diagnostics of the final structure (issue #33)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import comparison, factors, glm, large_claims, metrics
from health_pricing.models import diagnostics as dg
from health_pricing.models import frame as mf


def toy(n=800, seed=9, households=200) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cost = np.where(rng.random(n) < 0.4, rng.gamma(2.0, 1500.0, n), 0.0)
    return pd.DataFrame(
        {
            "DUID": rng.integers(0, households, n),
            "exposure": rng.uniform(0.3, 1.0, n),
            "cost": cost,
            "capped_cost": np.minimum(cost, 5000.0),
            "claimant": (cost > 0).astype(int),
        }
    )


def predicted_for(frame) -> np.ndarray:
    return frame["exposure"].to_numpy() * (frame["cost"].sum() / frame["exposure"].sum())


def test_residuals_have_the_sign_and_size_of_the_deviance_by_hand():
    frame = pd.DataFrame(
        {"cost": [100.0, 0.0, 50.0], "exposure": [1.0, 1.0, 1.0], "DUID": [1, 2, 3]}
    )
    predicted = np.array([80.0, 30.0, 70.0])
    table = dg.residual_summary(frame, predicted, n=3)
    unit = metrics.tweedie_unit_deviance(frame["cost"], predicted)
    expected = np.sign(frame["cost"] - predicted) * np.sqrt(unit)
    # one person-year per group, ordered by predicted cost 30, 70, 80
    assert table["person_years"].tolist() == [1, 1, 1]
    assert table["claimants"].tolist()[1:] == [1, 1] and pd.isna(table["claimants"].iloc[0])
    assert table["mean_deviance"].tolist() == pytest.approx([unit[1], unit[2], unit[0]])
    assert table["mean_residual_claimants"].iloc[1] == pytest.approx(expected[2])
    assert table["mean_residual_claimants"].iloc[2] == pytest.approx(expected[0])
    assert table["mean_residual_claimants"].iloc[1] < 0 < table["mean_residual_claimants"].iloc[2]


def test_a_person_year_without_cost_has_the_residual_of_minus_twice_the_prediction_root():
    unit = metrics.tweedie_unit_deviance([0.0], [16.0], 1.5)
    assert -np.sqrt(unit[0]) == pytest.approx(-2 * 16.0**0.25)


def test_residual_summary_covers_every_row_in_ten_groups():
    frame = toy()
    table = dg.residual_summary(frame, predicted_for(frame))
    assert len(table) == 10 and table["person_years"].sum() == len(frame)
    assert table["claimants"].sum() == (frame["cost"] > 0).sum()
    assert table["share_claimants_beyond_2"].between(0, 1).all()


def test_lift_groups_hold_the_right_totals_and_the_a_e_by_hand():
    frame = toy()
    predicted = predicted_for(frame)
    table = dg.lift_with_bands(frame, predicted, n=5, n_boot=200)
    assert table["person_years"].sum() == len(frame)
    assert table["actual"].sum() == pytest.approx(frame["cost"].sum())
    assert table["predicted"].sum() == pytest.approx(predicted.sum())
    reference = metrics.lift_table(frame["cost"], predicted, frame["exposure"], 5)
    assert table["a_e"].tolist() == pytest.approx(reference["a_e"].tolist())
    assert (table["lower_95"] < table["upper_95"]).all()


def test_a_single_household_gives_no_resampling_spread():
    frame = toy().assign(DUID=1)
    table = dg.lift_with_bands(frame, predicted_for(frame), n=5, n_boot=100)
    assert table["lower_95"].tolist() == pytest.approx(table["a_e"].tolist())
    assert table["upper_95"].tolist() == pytest.approx(table["a_e"].tolist())


def test_the_bands_are_reproducible_and_narrow_with_more_data():
    small = toy(n=400, households=100)
    large = toy(n=6400, households=1600)
    first = dg.lift_with_bands(small, predicted_for(small), n=5, n_boot=300)
    again = dg.lift_with_bands(small, predicted_for(small), n=5, n_boot=300)
    assert first["lower_95"].tolist() == again["lower_95"].tolist()
    big = dg.lift_with_bands(large, predicted_for(large), n=5, n_boot=300)
    assert (big["upper_95"] - big["lower_95"]).mean() < (
        first["upper_95"] - first["lower_95"]
    ).mean()


def test_end_groups_report_the_lowest_and_highest_group():
    lift = pd.DataFrame(
        {
            "split": "test",
            "model": "final",
            "groups": 3,
            "group": [1, 2, 3],
            "a_e": [0.5, 1.0, 0.8],
        }
    )
    row = dg.end_groups(lift).iloc[0]
    assert row["lowest_group_a_e"] == 0.5 and row["highest_group_a_e"] == 0.8
    assert row["top_predicted_over_actual"] == pytest.approx(0.25)


def test_overall_check_applies_the_tolerances_and_the_matched_load():
    train, test = toy(), toy(seed=10)
    prepared = mf.Frames(train, test, {})
    balanced = predicted_for(train)
    test_prediction = predicted_for(test) * 1.2
    candidate = comparison.Candidate("t", 3, balanced, test_prediction, balanced, test_prediction)
    result = factors.OptionResult(candidate, 1.0, 1)
    table = dg.overall_check(prepared, result, n_boot=200).set_index("split")
    assert table.loc["train", "a_e"] == pytest.approx(1.0)
    assert table.loc["train", "within_tolerance"]
    assert table.loc["test", "tolerance"] == 0.05
    assert not table.loc["test", "within_tolerance"]  # 1/1.2 is outside 5 percent
    capped = large_claims.capped_cost(test["cost"])
    own = (test["cost"] - capped).sum() / capped.sum()
    assert table.loc["test", "own_excess_load"] == pytest.approx(own)
    assert table.loc["test", "a_e_if_load_matched"] == pytest.approx(
        table.loc["test", "a_e"] * 1.065 / (1 + own)
    )
    assert table.loc["test", "lower_95"] < table.loc["test", "a_e"] < table.loc["test", "upper_95"]


def test_roles_and_flags_follow_the_final_structure():
    assert dg.factor_role("age") == "rating"
    assert dg.factor_role("rthlth") == "analysis_only"
    assert dg.factor_role("OFTSMK53") == "analysis_only"
    assert dg.factor_role("MIDX") == "dropped"
    table = pd.DataFrame(
        {
            "split": ["test"] * 4,
            "factor": ["MIDX", "age", "rthlth", "age"],
            "level": ["1", "05-14", "1", "00-04"],
            "role": ["dropped", "rating", "analysis_only", "rating"],
            "claimants": [100, 100, 100, 10],
            "a_e": [1.5, 1.4, 0.7, 2.0],
        }
    )
    table["enough_claimants"] = table["claimants"] >= dg.MIN_CLAIMANTS
    out_of_band = (table["a_e"] < dg.AE_LOW) | (table["a_e"] > dg.AE_HIGH)
    table["outside_band"] = table["enough_claimants"] & out_of_band
    flagged = dg.flagged_levels(table)
    assert flagged["role"].tolist() == ["rating", "analysis_only", "dropped"]
    assert "00-04" not in set(flagged["level"])  # only 10 claimants
    summary = dg.flag_summary(table).set_index(["split", "role"])
    assert summary.loc[("test", "rating"), "levels_checked"] == 1


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
def test_real_final_structure_is_balanced_on_train_and_tables_have_every_factor():
    prepared = glm.prepare_frames(mf.load_frames())
    final = dg.final_result(prepared)
    assert final.rating_factors == 9
    check = dg.overall_check(prepared, final, n_boot=200).set_index("split")
    assert check.loc["train", "a_e"] == pytest.approx(1.0)
    assert check.loc["train", "within_tolerance"]
    table = dg.ae_by_level(prepared, final)
    assert set(table["factor"]) == set(mf.FACTORS) and set(table["split"]) == {"train", "test"}
    assert set(table["role"]) == {"rating", "analysis_only", "dropped"}
    lift = dg.lift_by_split(prepared, {"final": final}, n_groups=(5,))
    assert set(lift["groups"]) == {5} and len(lift) == 10
