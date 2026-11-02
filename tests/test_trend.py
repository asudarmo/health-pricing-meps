"""Tests for the frequency trend and the decomposition of the 2023 gap (M5, issue #43)."""

import duckdb
import numpy as np
import pandas as pd
import pytest

from health_pricing.data import urr
from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import large_claims, outofsample, trend


def synthetic(n=600, seed=1, households=150, shift=1.0) -> trend.Parts:
    rng = np.random.default_rng(seed)
    t = rng.uniform(0.3, 1.0, n)
    p = np.clip(rng.uniform(0.1, 0.8, n) * shift, 0.01, 0.95)
    mu = rng.uniform(500, 4000, n)
    N = (rng.random(n) < p).astype(float)
    Y = N * rng.gamma(2.0, mu / 2.0)
    S = np.minimum(Y, 6000.0)
    frame = pd.DataFrame({"DUID": rng.integers(0, households, n), "claim_count": N})
    return trend.Parts(frame, t, N, S, Y, p, mu, pd.factorize(frame["DUID"])[0])


def test_a_hazard_trend_keeps_the_probability_below_one_and_is_monotone():
    p = np.array([0.0, 0.2, 0.9, 0.999])
    assert trend.hazard_trend(p, 1.0).tolist() == pytest.approx(p.tolist())
    assert (trend.hazard_trend(p, 1.5) <= 1).all()
    assert (trend.hazard_trend(p, 1.1) >= p).all() and (trend.hazard_trend(p, 0.9) <= p).all()
    # a hazard of 1.05 on a small probability is a rise of about 5 percent
    assert trend.hazard_trend(np.array([0.01]), 1.05)[0] == pytest.approx(0.0105, rel=1e-2)


def test_the_four_components_multiply_to_the_total_ratio_exactly():
    train, later = synthetic(), synthetic(seed=2, shift=1.2)
    table = trend.decomposition(train, later, n_boot=200).set_index("component")
    parts = table["ratio"].iloc[:4]
    assert parts.prod() == pytest.approx(table["ratio"].iloc[4], rel=1e-12)
    actual = (later.Y.sum() / later.t.sum()) / (train.Y.sum() / train.t.sum())
    assert table["ratio"].iloc[4] == pytest.approx(actual, rel=1e-12)
    assert table["share_of_log_gap"].iloc[:4].sum() == pytest.approx(1.0)
    assert (table["lower_95_percent"] < table["upper_95_percent"]).all()


def test_each_component_is_its_definition_by_hand():
    train, later = synthetic(), synthetic(seed=3, shift=1.1)
    table = trend.decomposition(train, later, n_boot=100).set_index("component")

    def mix(x):
        return (x.p * x.mu).sum() / x.t.sum()

    def frequency(x):
        return x.N.sum() / x.p.sum()

    def severity(x):
        return (x.S.sum() / x.N.sum()) / ((x.p * x.mu).sum() / x.p.sum())

    def large(x):
        return x.Y.sum() / x.S.sum()

    expected = [mix, frequency, severity, large]
    for line, function in zip(table["ratio"].iloc[:4], expected, strict=True):
        assert line == pytest.approx(function(later) / function(train))


def test_the_bootstrap_is_reproducible_and_the_same_periods_give_ratios_of_one():
    pieces = synthetic()
    again = trend.decomposition(pieces, pieces, n_boot=100)
    assert again["ratio"].tolist() == pytest.approx([1.0] * 5)
    first = trend.decomposition(pieces, synthetic(seed=4), n_boot=100)
    second = trend.decomposition(pieces, synthetic(seed=4), n_boot=100)
    assert first["lower_95_percent"].tolist() == second["lower_95_percent"].tolist()


def test_the_implied_hazard_factor_recovers_a_known_trend():
    train = synthetic()
    later = synthetic(seed=5)
    # make the later period's claimants match a hazard factor of 1.12 on its own probabilities
    calibration = train.p.sum() / train.N.sum()
    later.N = later.N * 0 + ((trend.hazard_trend(later.p, 1.12).sum() / calibration) / len(later.p))
    assert trend.implied_hazard_factor(train, later) == pytest.approx(1.12, rel=1e-6)


def test_forecast_mode_must_be_cost_or_hazard():
    with pytest.raises(ValueError):
        trend.forecast_prediction(None, None, None, 1.02, "other")


def test_the_tariff_carries_the_technical_models_average_rise_for_a_hazard_factor():
    class Frozen:
        balance = 1.2

    pieces = synthetic()
    rise = trend.level_equivalent(Frozen(), pieces, 1.05)
    assert 1.0 < rise < 1.05  # a high probability rises by less than the hazard
    assert trend.level_equivalent(Frozen(), pieces, 1.0) == pytest.approx(1.0)
    low = trend.Parts(**{**pieces.__dict__, "p": np.full(len(pieces.p), 0.001)})
    assert trend.level_equivalent(Frozen(), low, 1.05) == pytest.approx(1.05, rel=1e-3)


def test_load_check_scales_by_the_ratio_of_the_loads():
    class Frozen:
        balance = 1.1

    pieces = synthetic()
    own = large_claims.PROVISIONAL_LOAD
    check = trend.load_check(Frozen(), pieces, own)
    assert check["a_e_if_load_matched"] == pytest.approx(check["a_e_provisional_load"])
    assert check["change_in_a_e_points"] == pytest.approx(0.0)
    check = trend.load_check(Frozen(), pieces, 0.12)
    ratio = (1 + 0.12) / (1 + large_claims.PROVISIONAL_LOAD)
    assert check["a_e_if_load_matched"] == pytest.approx(check["a_e_provisional_load"] / ratio)


def test_weighted_quantile_uses_member_months():
    values = pd.Series([1.0, 2.0, 3.0])
    assert urr.weighted_quantile(values, pd.Series([1, 1, 1]), 0.5) == 2.0
    assert urr.weighted_quantile(values, pd.Series([1, 1, 10]), 0.5) == 3.0
    assert urr.weighted_quantile(values, pd.Series([10, 1, 1]), 0.5) == 1.0


def test_only_calendar_2021_experience_filings_with_member_months_are_forecasts():
    sheet = pd.DataFrame(
        {
            "EXP_BEG_DT": ["01/01/2021", "01/01/2021", "07/01/2020", "01/01/2021"],
            "PRJ_BEG_DT": ["01/01/2023", "01/01/2023", "01/01/2023", "07/01/2022"],
            "EXP_MM_WK1": [100.0, 0.0, 100.0, 100.0],
        }
    )
    assert urr.forecast_filings(sheet).index.tolist() == [0]


def test_the_trend_is_a_blend_of_inpatient_and_outpatient_by_claims_share():
    sheet = pd.DataFrame(
        {
            "EXP_BEG_DT": ["01/01/2021"] * 3,
            "PRJ_BEG_DT": ["01/01/2023"] * 3,
            "MARKET": ["Individual", "Individual", "Small Group"],
            "EXP_MM_WK1": [100.0, 100.0, 100.0],
            "EXP_IDX_RT_INP": [100.0, 100.0, 100.0],
            "EXP_IDX_RT_OUT": [300.0, 300.0, 300.0],
            "YR2_TRND_UTIL_INP": [1.00, 1.00, 1.00],
            "YR2_TRND_UTIL_OUT": [1.04, 1.04, 1.04],
        }
    )
    table = urr.utilization_trends(sheet).set_index(["market", "category"])
    # one quarter inpatient and three quarters outpatient
    assert table.loc[("all", "blend"), "p50"] == pytest.approx(0.25 * 1.00 + 0.75 * 1.04)
    assert table.loc[("individual", "inpatient"), "filings"] == 2
    assert table.loc[("small group", "outpatient"), "p50"] == 1.04


@pytest.mark.skipif(not urr.URR_ZIP.exists(), reason="run python -m health_pricing.data.urr")
def test_the_downloaded_urr_file_matches_its_checksum_and_gives_the_recorded_trends():
    urr.download()  # checks the size and the checksum
    table = urr.utilization_trends(urr.read_worksheet1()).set_index(["market", "category"])
    row = table.loc[("all", "blend")]
    assert row["filings"] == 713
    assert round(row["p50"], 3) == 1.019 and round(row["p25"], 3) == 1.008
    assert round(row["p75"], 3) == 1.031
    assert round(table.loc[("all", "inpatient"), "p50"], 3) == 1.015
    assert round(table.loc[("all", "outpatient"), "p50"], 3) == 1.025


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


@pytest.fixture(scope="module")
def frozen():
    return outofsample.freeze()


@pytest.fixture(scope="module")
def oot(frozen):
    return outofsample.load_out_of_time(frozen)


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_real_decomposition_multiplies_to_the_16_9_percent_gap(frozen, oot):
    train, later = trend.train_parts(frozen), trend.out_of_time_parts(frozen, oot)
    table = trend.decomposition(train, later, n_boot=200).set_index("component")
    assert table["ratio"].iloc[:4].prod() == pytest.approx(table["ratio"].iloc[4], rel=1e-12)
    assert table["change_percent"].iloc[4] == pytest.approx(16.88, abs=0.02)
    assert table["change_percent"].iloc[2] == pytest.approx(13.93, abs=0.05)  # severity
    assert table["change_percent"].iloc[1] == pytest.approx(2.73, abs=0.05)  # frequency
    assert abs(table["change_percent"].iloc[0]) < 0.5  # mix
    assert table["change_percent"].iloc[3] < 0  # large claims


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_real_trend_options_scale_a_e_by_the_factor_and_the_parts_multiply(frozen, oot):
    options = {
        "none": (1.0, "cost", "no trend", "sensitivity"),
        "urr": (1.019, "cost", "URR", "central"),
        "hazard": (1.019, "hazard", "URR", "comparison"),
        "high": (1.031, "cost", "URR", "range"),
    }
    table = trend.trend_options(frozen, oot, options, n_boot=200).set_index("option")
    assert table.loc["none", "technical_a_e"] == pytest.approx(1.1671, abs=5e-4)
    assert table.loc["none", "tariff_a_e"] == pytest.approx(1.1670, abs=5e-4)
    # a trend on expected cost divides the A/E by the factor, a hazard trend by less
    assert table.loc["urr", "technical_a_e"] == pytest.approx(
        table.loc["none", "technical_a_e"] / 1.019
    )
    assert table.loc["urr", "tariff_a_e"] == pytest.approx(table.loc["none", "tariff_a_e"] / 1.019)
    assert table.loc["hazard", "technical_a_e"] > table.loc["urr", "technical_a_e"]
    assert table.loc["high", "technical_a_e"] < table.loc["urr", "technical_a_e"]
    assert (table["technical_lower_95"] < table["technical_a_e"]).all()
    # the product of the three ratios is the technical A/E
    train, later = trend.train_parts(frozen), trend.out_of_time_parts(frozen, oot)
    parts = trend.ae_components(frozen, oot, train, later, n_boot=200).set_index("measure")
    product = parts["value"].iloc[2:5].prod()
    assert product == pytest.approx(parts.loc["Technical model A/E", "value"], rel=1e-6)
    implied = trend.implied_hazard_factor(train, later)
    assert 1.0 < implied < 1.08
    check = trend.load_check(frozen, later, 0.0616)
    assert (
        check["change_in_a_e_points"] > 0
    )  # the load is already high enough, so no gap is explained


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_real_frequency_table_covers_every_age_group_and_period(frozen, oot):
    table = trend.frequency_table(frozen, oot, n_boot=100)
    assert set(table["group"]) == {"All", "Children", "18-39", "40-64", "65+"}
    assert set(table["period"]) == {"2022 train", "2022 test", "2023"}
    sizes = table[table["period"] == "2023"].set_index("group")["person_years"]
    assert sizes.drop("All").sum() == sizes["All"]
    row = table[(table["group"] == "All") & (table["period"] == "2023")].iloc[0]
    assert row["claimant_rate_vs_2022_train_lower_95"] < row["claimant_rate_vs_2022_train"]
    assert row["claimant_rate_vs_2022_train"] < row["claimant_rate_vs_2022_train_upper_95"]
