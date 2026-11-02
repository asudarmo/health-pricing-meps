"""Tests for the two-part GLM candidates (issues #28 and #29)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import frame as mf
from health_pricing.models import glm, large_claims
from health_pricing.models.frame import Frames

FACTORS = ["a", "b"]


def synthetic(n=800, seed=7, extra=None) -> pd.DataFrame:
    """Person-years with two factors, a claim count that is pure noise, and capped cost."""
    rng = np.random.default_rng(seed)
    a = rng.choice(["r", "x", "y"], n, p=[0.5, 0.3, 0.2])
    b = rng.choice(["r", "z"], n, p=[0.6, 0.4])
    exposure = rng.uniform(0.2, 1.0, n)
    rate = (
        0.4 * np.where(a == "x", 1.5, 1.0) * np.where(a == "y", 0.6, 1.0) * np.where(b == "z", 2, 1)
    )
    claimed = rng.random(n) < 1 - np.exp(-rate * exposure)
    cost = np.where(claimed, rng.gamma(2.0, 1500.0 * np.where(b == "z", 1.5, 1.0)), 0.0)
    frame = pd.DataFrame(
        {
            "a": pd.Categorical(a, categories=["r", "x", "y"]),
            "b": pd.Categorical(b, categories=["r", "z"]),
            "exposure": exposure,
            "capped_cost": cost,
            "cost": cost,
            "claim_count": rng.integers(0, 9, n),
        }
    )
    for name, value in (extra or {}).items():
        frame[name] = value
    return frame


def fit(frame, link="cloglog", **kwargs):
    return glm.fit_two_part(frame, link, FACTORS, **kwargs)


def profile(exposure=0.5, a="x", b="z") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": pd.Categorical([a], categories=["r", "x", "y"]),
            "b": pd.Categorical([b], categories=["r", "z"]),
            "exposure": [exposure],
        }
    )


def linear(result, terms) -> float:
    return float(sum(result.params[t] for t in terms))


@pytest.mark.parametrize("link", ["cloglog", "poisson"])
def test_prediction_is_expected_claimants_times_severity_for_a_hand_made_profile(link):
    model = fit(synthetic(), link)
    row = profile(exposure=0.5)
    terms = ["const", "a=x", "b=z"]
    eta = linear(model.frequency, terms) + np.log(0.5)
    claimants = 1 - np.exp(-np.exp(eta)) if link == "cloglog" else np.exp(eta)
    severity = np.exp(linear(model.severity, terms))
    assert model.expected_claimants(row)[0] == pytest.approx(claimants)
    assert model.expected_severity(row)[0] == pytest.approx(severity)
    assert model.predict_capped(row)[0] == pytest.approx(claimants * severity)
    assert model.predict(row)[0] == pytest.approx(claimants * severity * 1.065)
    assert model.predict(row, load=0.0)[0] == pytest.approx(claimants * severity)


def test_exposure_enters_through_the_offset_and_not_the_severity():
    cloglog, poisson = fit(synthetic()), fit(synthetic(), "poisson")
    half, whole = profile(exposure=0.5), profile(exposure=1.0)
    p_half, p_whole = cloglog.expected_claimants(half)[0], cloglog.expected_claimants(whole)[0]
    # with a cloglog link and an offset, survival over a year is survival over half a year squared
    assert 1 - p_whole == pytest.approx((1 - p_half) ** 2)
    assert poisson.expected_claimants(whole)[0] == pytest.approx(
        2 * poisson.expected_claimants(half)[0]
    )
    assert cloglog.expected_severity(half)[0] == cloglog.expected_severity(whole)[0]
    # the offset has a fixed coefficient, so it is not among the estimated terms
    assert not any("exposure" in term for term in cloglog.frequency.params.index)


def test_the_claim_count_is_neither_a_weight_nor_a_predictor():
    frame = synthetic()
    base = fit(frame)
    shuffled = frame.assign(claim_count=np.random.default_rng(1).permutation(frame["claim_count"]))
    other = fit(shuffled)
    assert "claim_count" not in glm.design_matrix(frame, FACTORS).columns
    for part in ("frequency", "severity"):
        assert np.allclose(getattr(base, part).params, getattr(other, part).params)
        assert getattr(base, part).model.freq_weights.min() == 1.0
        assert getattr(base, part).model.freq_weights.max() == 1.0
    # and the fit does not even need the column
    without = fit(frame.drop(columns=["claim_count", "cost"]))
    assert np.allclose(base.frequency.params, without.frequency.params)


def test_the_cloglog_probability_cannot_exceed_one_and_the_poisson_mean_can():
    rng = np.random.default_rng(3)
    frame = synthetic(n=400).assign(exposure=1.0)
    frame["capped_cost"] = np.where(frame["b"] == "z", rng.gamma(2, 900, 400), frame["capped_cost"])
    cloglog, poisson = fit(frame), fit(frame, "poisson")
    assert (cloglog.expected_claimants(frame) <= 1).all()
    assert poisson.expected_claimants(frame).max() > cloglog.expected_claimants(frame).max()


def test_unknown_is_a_control_in_the_fit_and_priced_at_the_reference():
    frame = synthetic()
    frame["OFTSMK53"] = pd.Categorical(["3"] * len(frame), categories=["3", "unknown"])
    frame["PHYEXE53"] = pd.Categorical(["1"] * len(frame), categories=["1", "unknown"])
    leavers = frame.index[:40]
    for column in ("OFTSMK53", "PHYEXE53"):
        frame.loc[leavers, column] = "unknown"
    factors = [*FACTORS, "OFTSMK53", "PHYEXE53"]
    fitted = glm.design_matrix(frame, factors)
    assert fitted["unknown_control"].sum() == 40
    assert not any(column.endswith("=unknown") for column in fitted)
    rating = glm.design_matrix(frame, factors, rating=True)
    assert rating["unknown_control"].sum() == 0
    model = glm.fit_two_part(frame, "cloglog", factors)
    assert "unknown_control" in model.frequency.params
    leaver, stayer = frame.loc[[0]], frame.loc[[0]].assign()
    stayer["OFTSMK53"] = pd.Categorical(["3"], categories=["3", "unknown"])
    stayer["PHYEXE53"] = pd.Categorical(["1"], categories=["1", "unknown"])
    assert model.predict(leaver)[0] == pytest.approx(model.predict(stayer)[0])


def test_a_rank_deficient_design_is_refused():
    frame = synthetic()
    frame["c"] = frame["a"]  # an exact copy of a factor
    with pytest.raises(ValueError, match="rank"):
        glm.fit_two_part(frame, "cloglog", [*FACTORS, "c"])


def test_coefficient_table_counts_claimants_in_every_level():
    frame = synthetic()
    table = glm.coefficient_table(fit(frame), frame)
    claimed = frame["capped_cost"] > 0
    freq = table[table["part"] == "frequency"].set_index("term")
    assert freq.loc["const", "claimants"] == claimed.sum()
    assert freq.loc["a=x", "claimants"] == (claimed & (frame["a"] == "x")).sum()
    assert freq.loc["b=z", "claimants"] == (claimed & (frame["b"] == "z")).sum()
    assert set(table["part"]) == {"frequency", "severity"}
    assert (table["std_error"] > 0).all()
    assert table["relativity"].tolist() == pytest.approx(np.exp(table["coefficient"]).tolist())


def test_the_gamma_dispersion_is_reported():
    assert fit(synthetic()).dispersion == pytest.approx(0.5, abs=0.2)  # shape 2 gives 1/2


def test_deviance_test_matches_a_hand_calculation():
    frame = synthetic().assign(noise=lambda d: np.arange(len(d)) % 3)
    frame["noise"] = pd.Categorical(frame["noise"].astype(str))
    small = glm.fit_two_part(frame, "cloglog", FACTORS)
    big = glm.fit_two_part(frame, "cloglog", [*FACTORS, "noise"])
    out = glm.deviance_test(small, big, "frequency")
    assert out["df"] == 2
    assert out["statistic"] == pytest.approx(small.frequency.deviance - big.frequency.deviance)
    assert 0 <= out["p_value"] <= 1
    sev = glm.deviance_test(small, big, "severity")
    assert sev["statistic"] == pytest.approx(
        (small.severity.deviance - big.severity.deviance) / big.severity.scale
    )


def test_probability_calibration_groups_cover_every_person_year():
    rng = np.random.default_rng(0)
    p = rng.random(500)
    table = glm.probability_calibration(rng.random(500) < p, p)
    assert table["person_years"].sum() == 500
    assert len(table) == 10
    assert table["mean_predicted"].is_monotonic_increasing


def test_candidate_scores_use_the_uncapped_cost_and_save_aggregates(tmp_path):
    frame = synthetic()
    predicted = np.full(len(frame), frame["cost"].mean())
    scores = glm.candidate_scores("x", 5, {"train": (frame.assign(claimant=0), predicted)})
    assert list(scores.columns) == glm.SCORE_COLUMNS
    assert scores.loc[0, "parameters"] == 5 and scores.loc[0, "a_e"] == pytest.approx(1.0)
    path = glm.save_scores(scores, "x", tmp_path)
    assert pd.read_csv(path).shape == (1, len(glm.SCORE_COLUMNS))


def test_prepare_frames_groups_levels_and_caps_cost_without_changing_cost():
    rows = []
    for i in range(12):
        row = {
            "DUPERSID": f"p{i}", "DUID": i, "year": 2022, "split": "train" if i < 9 else "test",
            "age": 30 + i, "exposure": 1.0, "claim_count": 1,
            "claim_cost_2023_prices": 5e5 if i == 0 else 100.0,
            "region": 1, "inscov": 1, "rthlth": 2, "mnhlth": 2, "OFTSMK53": "3", "PHYEXE53": "1",
        }  # fmt: skip
        row.update({c: "0" for c in mf.FACTORS if c not in row})
        rows.append(row)
    frames = mf.build_frames(pd.DataFrame(rows))
    prepared = glm.prepare_frames(frames)
    assert prepared.train["capped_cost"].max() == large_claims.LARGE_CLAIM_CAP
    assert prepared.train["cost"].max() == 5e5
    assert prepared.train["age"].cat.categories[0] == prepared.reference_levels["age"]


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
def test_candidates_a_and_b_beat_the_baseline_on_the_real_holdout():
    from health_pricing.models import metrics

    raw = mf.load_frames()
    frames = glm.prepare_frames(raw)
    assert isinstance(frames, Frames) and frames.train["capped_cost"].max() <= 100_000
    baseline = metrics.baseline_scores(raw.train, raw.test).set_index("split")
    for link in glm.FREQUENCY_LINKS:
        model = glm.fit_two_part(frames.train, link)
        assert (model.expected_claimants(frames.train) <= 1).all() or link == "poisson"
        scores = glm.candidate_scores(
            link, model.parameters, {"test": (frames.test, model.predict(frames.test))}
        )
        assert scores.loc[0, "tweedie_deviance"] < baseline.loc["test", "tweedie_deviance"]
        assert scores.loc[0, "gini"] > 0.3


def test_wide_coefficients_keep_the_term_order_and_both_parts():
    frame = synthetic()
    table = glm.coefficient_table(fit(frame), frame)
    wide = glm.wide_coefficients(table)
    assert list(wide.index) == list(dict.fromkeys(table["term"]))
    assert set(wide.columns.get_level_values(0)) == {"frequency", "severity"}
    assert wide.loc["a=x", ("frequency", "coefficient")] == pytest.approx(
        table[(table["part"] == "frequency") & (table["term"] == "a=x")]["coefficient"].iloc[0]
    )
