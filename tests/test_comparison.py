"""Tests for the model comparison (issue #32)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import comparison as cmp
from health_pricing.models import glm, metrics
from health_pricing.models.frame import Frames

LOAD = 1.065


def toy(n=600, seed=5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    a = rng.choice(["r", "x", "y"], n)
    b = rng.choice(["r", "z"], n)
    cost = np.where(rng.random(n) < 0.4, rng.gamma(2.0, 1500.0, n), 0.0)
    return pd.DataFrame(
        {
            "a": pd.Categorical(a, categories=["r", "x", "y"]),
            "b": pd.Categorical(b, categories=["r", "z"]),
            "DUID": rng.integers(0, 150, n),
            "exposure": rng.uniform(0.3, 1.0, n),
            "cost": cost,
            "capped_cost": np.minimum(cost, 5000.0),
            "claimant": (cost > 0).astype(int),
            "claim_count": (cost > 0).astype(int),
        }
    )


def candidate(name, train, test=None, parameters=3) -> cmp.Candidate:
    test = train if test is None else test
    return cmp.Candidate(name, parameters, train, test, train, test)


def test_unit_deviances_add_up_to_the_total():
    y = np.array([0.0, 100.0, 2500.0])
    mu = np.array([50.0, 120.0, 2000.0])
    units = metrics.tweedie_unit_deviance(y, mu, 1.5)
    assert units.shape == (3,) and (units >= 0).all()
    assert units.sum() == pytest.approx(metrics.tweedie_deviance(y, mu, 1.5))


def test_an_exactly_multiplicative_prediction_has_no_departure():
    frame = toy()
    matrix = glm.design_matrix(frame, ["a", "b"])
    relativity = {"x": 1.4, "y": 0.7, "z": 2.0}
    prediction = (
        900.0
        * frame["a"].astype(object).map(relativity).fillna(1.0)
        * frame["b"].astype(object).map(relativity).fillna(1.0)
    )
    out = cmp.multiplicative_departure(prediction.to_numpy(), matrix)
    assert out["max_multiplicative_departure"] < 1e-9
    assert out["rms_log_departure"] < 1e-9


def test_an_interaction_shows_as_a_departure_from_the_multiplicative_form():
    frame = toy()
    matrix = glm.design_matrix(frame, ["a", "b"])
    both = (frame["a"] == "x") & (frame["b"] == "z")
    prediction = np.where(both, 3000.0, 1000.0)
    out = cmp.multiplicative_departure(prediction, matrix)
    # the best multiplicative form cannot reproduce a cell that is three times the rest
    assert out["max_multiplicative_departure"] > 0.2
    assert out["p99_multiplicative_departure"] <= out["max_multiplicative_departure"]


def test_ranking_orders_by_deviance_at_each_power():
    table = pd.DataFrame(
        {
            "candidate": ["a", "b", "a", "b"],
            "split": ["test", "test", "train", "train"],
            "tweedie_deviance_p1_3": [3.0, 2.0, 1.0, 9.0],
            "tweedie_deviance": [1.0, 2.0, 1.0, 9.0],
            "tweedie_deviance_p1_7": [1.0, 2.0, 1.0, 9.0],
        }
    )
    ranks = cmp.ranking_table(table).set_index("candidate")
    assert ranks.loc["a", "rank_p1_5"] == 1 and ranks.loc["b", "rank_p1_5"] == 2
    assert ranks.loc["b", "rank_p1_3"] == 1  # the order can differ at another power


def test_flags_need_enough_claimants_and_an_a_e_outside_the_band():
    frame = toy(n=800)
    predicted = frame["cost"].mean() * frame["exposure"].to_numpy() / frame["exposure"].mean()
    predicted = np.where(frame["a"] == "x", predicted * 3, predicted)  # x is badly over-predicted
    flags = cmp.ae_flags(frame, predicted, ["a", "b"], name="t")
    assert set(flags["candidate"]) == {"t"} and (flags["claimants"] >= 30).all()
    assert "x" in set(flags.loc[flags["factor"] == "a", "level"])
    assert ((flags["a_e"] < 0.85) | (flags["a_e"] > 1.15)).all()


def test_the_capped_view_scores_against_capped_cost_without_the_load(monkeypatch):
    monkeypatch.setattr(cmp, "FACTORS", ["a", "b"])
    frame = toy()
    perfect = candidate("p", frame["capped_cost"].to_numpy() * LOAD + 1e-9)
    counts = cmp.ae_flag_counts(frame, {"p": perfect}, "train", capped=True)
    assert counts.loc[0, "levels_outside_band"] == 0
    assert counts.loc[0, "worst_a_e"] == pytest.approx(1.0, abs=1e-6)
    uncapped = cmp.ae_flag_counts(frame, {"p": perfect}, "train", capped=False)
    assert uncapped.loc[0, "worst_a_e"] != pytest.approx(1.0, abs=1e-3)


def test_lift_comparison_has_a_column_per_candidate():
    frame = toy()
    pred = frame["exposure"].to_numpy() * 1000.0
    table = cmp.lift_comparison(
        frame, {"p": candidate("p", pred), "q": candidate("q", pred * 2)}, "train"
    )
    assert list(table.columns) == ["decile", "p", "q"] and len(table) == 10
    assert table["q"].tolist() == pytest.approx((table["p"] / 2).tolist())


def test_deviance_interval_is_zero_for_equal_candidates_and_positive_for_a_worse_one():
    frame = toy(n=1200)
    good = frame["capped_cost"].mean() * frame["exposure"].to_numpy() + 1.0
    worse = good * np.where(frame["a"] == "y", 4.0, 1.0)
    out = cmp.deviance_difference_interval(
        frame,
        {
            "a": candidate("a", good),
            "same": candidate("same", good),
            "bad": candidate("bad", worse),
        },
        "train",
        "a",
        n_boot=300,
    ).set_index("candidate")
    assert out.loc["same", "deviance_difference"] == 0 and out.loc["same", "upper_95"] == 0
    assert out.loc["bad", "deviance_difference"] > 0 and out.loc["bad", "lower_95"] > 0
    assert out.loc["bad", "share_better_than_reference"] == 0
    again = cmp.deviance_difference_interval(
        frame, {"a": candidate("a", good), "bad": candidate("bad", worse)}, "train", "a", n_boot=300
    ).set_index("candidate")
    assert again.loc["bad", "lower_95"] == out.loc["bad", "lower_95"]  # the seed is fixed


def test_the_comparison_table_has_the_agreed_columns_and_marks_unfitted_candidates(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cmp, "FACTORS", ["a", "b"])
    train, test = toy(), toy(seed=6)
    frames = Frames(train, test, {})
    predicted_train = train["exposure"].to_numpy() * 900
    predicted_test = test["exposure"].to_numpy() * 900
    fitted = cmp.Candidate("a", 3, predicted_train, predicted_test, predicted_train, predicted_test)
    table = cmp.comparison_table(frames, {"a": fitted})
    assert {cmp.BASELINE, "a", cmp.NAME_D} <= set(table["candidate"])
    assert "deviance_reduction_pct" in table.columns
    baseline_rows = table[table["candidate"] == cmp.BASELINE]
    assert (baseline_rows["deviance_reduction_pct"].abs() < 1e-9).all()
    assert set(table["split"]) == {"train", "test"}
    for column in ("tweedie_deviance", "gini", "a_e", "parameters", "dropped_reason"):
        assert column in table.columns
    dropped = table[table["candidate"] == "d"]
    assert dropped["tweedie_deviance"].isna().all() and (dropped["dropped_reason"] != "").all()
    path = cmp.save_comparison(table, tmp_path / "m" / "model_comparison.csv")
    assert pd.read_csv(path).shape[0] == len(table)


def _built() -> bool:
    import duckdb

    from health_pricing.data.load import DUCKDB_PATH

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
def test_real_comparison_matches_the_saved_candidate_scores_and_the_poisson_is_multiplicative():
    from health_pricing.models import frame as mf

    prepared, candidates = cmp.fit_candidates(mf.load_frames())
    table = cmp.comparison_table(prepared, candidates)
    assert set(candidates) == {cmp.NAME_A, cmp.NAME_B, cmp.NAME_C, cmp.NAME_C_AGE}
    saved = pd.read_csv(glm.SCORES_DIR / "scores_candidate_a.csv").set_index("split")
    row = table[(table["candidate"] == cmp.NAME_A) & (table["split"] == "test")].iloc[0]
    assert row["tweedie_deviance"] == pytest.approx(saved.loc["test", "tweedie_deviance"])
    departure = table.set_index(["candidate", "split"])["max_multiplicative_departure"]
    # log links on both parts and an offset make the Poisson candidate exactly multiplicative
    assert departure[(cmp.NAME_B, "test")] < 1e-6 and departure[(cmp.NAME_A, "test")] > 0.01


def test_overall_ae_interval_brackets_the_point_estimate_and_is_reproducible():
    frame = toy(n=1000)
    pred = frame["exposure"].to_numpy() * frame["cost"].sum() / frame["exposure"].sum()
    out = cmp.overall_ae_interval(frame, {"p": candidate("p", pred)}, "train", n_boot=400)
    row = out.iloc[0]
    assert row["a_e"] == pytest.approx(1.0)
    assert row["lower_95"] < row["a_e"] < row["upper_95"]
    again = cmp.overall_ae_interval(frame, {"p": candidate("p", pred)}, "train", n_boot=400)
    assert again.iloc[0]["lower_95"] == row["lower_95"]


def test_departure_table_has_a_row_per_candidate(monkeypatch):
    monkeypatch.setattr(cmp, "FACTORS", ["a", "b"])
    frame = toy()
    exact = np.exp(np.where(frame["a"] == "x", 0.3, 0.0) + np.where(frame["b"] == "z", 0.5, 0.0))
    kinked = np.where((frame["a"] == "x") & (frame["b"] == "z"), 5.0, 1.0)
    frames = Frames(frame, frame, {})
    out = cmp.departure_table(
        frames, {"exact": candidate("exact", exact), "kinked": candidate("kinked", kinked)}, "train"
    ).set_index("candidate")
    assert out.loc["exact", "max_multiplicative_departure"] < 1e-9
    assert out.loc["kinked", "max_multiplicative_departure"] > 0.2
