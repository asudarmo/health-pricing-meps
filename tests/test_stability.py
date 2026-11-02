"""Tests for the relativity stability comparison between 2022 and 2023 (M5, issue #45)."""

import duckdb
import numpy as np
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import outofsample, stability


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


def table(relativity, error, reference_first=True):
    rows = []
    for position, (value, se) in enumerate(zip(relativity, error, strict=True)):
        rows.append(
            {
                "factor": "f",
                "level": str(position),
                "role": "rating",
                "is_reference": position == 0 and reference_first,
                "relativity": value,
                "lower_95": value * np.exp(-1.96 * se),
                "upper_95": value * np.exp(1.96 * se),
                "log_error": se,
                "claimants": 10,
            }
        )
    return pd.DataFrame(rows)


def test_compare_gives_the_ratio_its_interval_and_z_and_skips_the_reference():
    earlier = table([1.0, 1.2, 2.0], [0.0, 0.1, 0.2])
    later = table([1.0, 1.2, 1.0], [0.0, 0.1, 0.2])
    out = stability.compare(earlier, later)
    assert out["level"].tolist() == ["1", "2"]
    assert out["ratio"].tolist() == pytest.approx([1.0, 0.5])
    error = np.sqrt(0.2**2 + 0.2**2)
    assert out["z"].iloc[1] == pytest.approx(np.log(0.5) / error)
    assert out["ratio_lower_95"].iloc[1] == pytest.approx(0.5 * np.exp(-1.96 * error), rel=1e-3)
    assert out["z"].iloc[0] == pytest.approx(0.0)


def test_beyond_noise_counts_the_differences_and_the_chance_expectation():
    z = [0.5, -2.5, 3.5, 0.1] + [0.0] * 16
    comparison = pd.DataFrame({"part": "combined", "role": "rating", "z": z})
    out = stability.beyond_noise(comparison).iloc[0]
    assert out["comparisons"] == 20
    assert out["beyond_noise"] == 2
    assert out["expected_by_chance"] == pytest.approx(1.0)
    assert 0.2 < out["p_value_that_many_by_chance"] < 0.3
    assert out["beyond_noise_after_bonferroni"] == 1


def test_levels_beyond_noise_are_sorted_by_size():
    comparison = pd.DataFrame({"z": [0.2, -3.0, 2.2], "level": ["a", "b", "c"]})
    assert stability.levels_beyond_noise(comparison)["level"].tolist() == ["b", "c"]


class Fit:
    def __init__(self, params, covariance):
        self.params = pd.Series(params)
        self._covariance = pd.DataFrame(
            covariance, index=self.params.index, columns=self.params.index
        )

    def cov_params(self):
        return self._covariance


def test_the_wald_test_ignores_the_constant_and_is_zero_for_equal_slopes():
    covariance = np.diag([1.0, 0.04, 0.04])
    earlier = Fit({"const": 0.0, "a": 0.3, "b": -0.2}, covariance)
    shifted = Fit({"const": 5.0, "a": 0.3, "b": -0.2}, covariance)
    statistic, df = stability._wald(earlier, shifted)
    assert (statistic, df) == pytest.approx((0.0, 2))
    moved = Fit({"const": 0.0, "a": 0.7, "b": -0.2}, covariance)
    statistic, _ = stability._wald(earlier, moved)
    assert statistic == pytest.approx(0.4**2 / 0.08)


pytestmark_real = pytest.mark.skipif(not _built(), reason="run the load script and dbt build")


@pytest.fixture(scope="module")
def setup():
    if not _built():
        pytest.skip("run the load script and dbt build")
    frozen = outofsample.freeze()
    oot = outofsample.load_out_of_time(frozen)
    refit = stability.refit_2023(frozen, oot)
    return frozen, oot, refit


@pytestmark_real
def test_the_refit_uses_the_2023_rows_and_the_same_structure(setup):
    frozen, oot, refit = setup
    assert refit.model.factors == frozen.spline.model.factors
    assert refit.model.numeric == frozen.spline.model.numeric
    expected = oot.spline_frame["claim_count"].gt(0).sum()
    assert refit.model.frequency.nobs == len(oot.spline_frame)
    assert refit.model.severity.nobs == int((oot.spline_frame["capped_cost"] > 0).sum())
    assert expected > 0
    predicted = refit.model.predict(oot.spline_frame)
    assert np.isfinite(predicted).all()


@pytestmark_real
def test_the_comparison_covers_every_level_and_the_tariff_is_rebased(setup):
    frozen, oot, refit = setup
    tables = stability.component_tables(frozen, oot, refit)
    comparison = stability.comparison_tables(tables)
    assert set(comparison["part"]) == {"frequency", "severity", "combined"}
    assert set(comparison["role"]) == {"rating", "analysis_only"}
    assert (comparison["ratio_lower_95"] <= comparison["ratio"]).all()
    tariff = stability.tariff_comparison(frozen, oot, refit)
    from health_pricing.models import relativities

    reference = relativities.age_reference_for_presentation(frozen.raw)
    assert reference not in set(tariff.loc[tariff["factor"] == "age", "level"])
    assert (tariff["ratio"] > 0).all()


@pytestmark_real
def test_the_age_curve_is_one_at_67_and_the_joint_tests_are_probabilities(setup):
    frozen, oot, refit = setup
    curve = stability.age_curve_comparison(frozen, refit)
    at_67 = curve[curve["age"] == 67].iloc[0]
    assert at_67["ratio"] == pytest.approx(1.0)
    assert at_67["ratio_upper_95"] - at_67["ratio_lower_95"] < 1e-6
    joint = stability.joint_tests(frozen, oot, refit)
    assert joint["p_value"].between(0, 1).all()
    assert (joint["level_shift"] > 0).all()
