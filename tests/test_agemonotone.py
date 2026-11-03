"""Tests for the monotone adult age rule of the tariff (M6, issue #57)."""

import duckdb
import numpy as np
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import agemonotone as am
from health_pricing.models import outofsample


def test_pava_pools_violations_to_the_weighted_mean_and_leaves_ordered_values():
    assert am.pava([1, 2, 3], [1, 1, 1]).tolist() == [1, 2, 3]
    out = am.pava([1.0, 4.0, 2.0, 5.0], [1, 1, 3, 1])
    assert out.tolist() == pytest.approx([1.0, 2.5, 2.5, 5.0])
    assert (np.diff(am.pava(np.random.default_rng(1).normal(size=40), np.ones(40))) >= 0).all()


def test_pava_keeps_the_weighted_total_and_a_full_reversal_pools_to_one_value():
    values, weights = np.array([5.0, 3.0, 1.0]), np.array([1.0, 2.0, 3.0])
    out = am.pava(values, weights)
    assert (out * weights).sum() == pytest.approx((values * weights).sum())
    assert np.allclose(out, out[0])


def test_adult_bands_are_ordered_by_age_and_children_are_left_out():
    levels = ["05-14", "00-04", "80+", "18-24", "65-69", "15-17", "25-29"]
    assert am.adult_bands(levels) == ["18-24", "25-29", "65-69", "80+"]
    assert am.lower_age("80+") == 80 and am.lower_age("05-14") == 5


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
    return frozen, am.adjust(frozen)


def test_adult_relativities_never_fall_and_children_and_young_adults_are_unchanged(setup):
    frozen, adjusted = setup
    table = am.band_table(frozen, adjusted)
    adult = table[table["adult"]]
    assert (adult["relativity_after"].diff().dropna() >= -1e-12).all()
    assert (table.loc[~table["adult"], "change_pct"].abs() < 1e-9).all()
    assert table.loc[table["age_band"] == "35-39", "change_pct"].abs().iloc[0] < 1e-9
    # the bands that broke the order are pooled and the rest are untouched
    assert table.loc[table["age_band"] == "80+", "change_pct"].iloc[0] > 0
    assert table.loc[table["age_band"] == "65-69", "change_pct"].iloc[0] < 0


def test_the_rebalanced_base_keeps_the_train_total_and_scores_are_close(setup):
    frozen, adjusted = setup
    train = frozen.prepared.train
    assert adjusted.predict(train).sum() == pytest.approx(frozen.tariff(train).sum(), rel=1e-9)
    scores = am.score_table(frozen, adjusted)
    test = scores[scores["split"] == "test"].set_index("candidate")
    gap = test.loc[am.ADJUSTED, "tweedie_deviance"] / test.loc[am.ORIGINAL, "tweedie_deviance"]
    assert abs(gap - 1) < 0.01
    ae = am.ae_by_band(frozen, adjusted)
    assert len(ae) == 16 and {"a_e_before", "a_e_after"} <= set(ae.columns)
