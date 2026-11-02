"""Tests for the PSI drift measures (M5, issue #46)."""

import duckdb
import numpy as np
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import drift, outofsample


def test_psi_is_zero_for_equal_shares_and_matches_a_hand_calculation():
    assert drift.psi(np.array([10.0, 30.0]), np.array([1.0, 3.0])) == pytest.approx(0.0)
    p, q = np.array([0.5, 0.5]), np.array([0.7, 0.3])
    expected = (0.7 - 0.5) * np.log(0.7 / 0.5) + (0.3 - 0.5) * np.log(0.3 / 0.5)
    assert drift.psi(p * 100, q * 40) == pytest.approx(expected)


def test_psi_is_symmetric_and_handles_an_empty_level_without_infinity():
    a, b = np.array([60.0, 40.0, 0.0]), np.array([40.0, 50.0, 10.0])
    assert drift.psi(a, b) == pytest.approx(drift.psi(b, a))
    assert np.isfinite(drift.psi(a, b))


def test_psi_works_along_the_last_axis():
    many = drift.psi(np.array([[1.0, 1.0], [1.0, 3.0]]), np.array([[1.0, 3.0], [1.0, 3.0]]))
    assert many[0] > 0 and many[1] == pytest.approx(0.0)


def test_reading_uses_the_conventional_bands():
    assert [drift.reading(v) for v in (0.05, 0.1, 0.2, 0.25, 0.3)] == [
        "below 0.1",
        "0.1 to 0.25",
        "0.1 to 0.25",
        "0.1 to 0.25",
        "above 0.25",
    ]


def test_weighted_edges_split_the_exposure_into_equal_parts():
    values = np.arange(1000, dtype=float)
    weights = np.ones(1000)
    edges = drift.weighted_edges(values, weights, 10)
    assert len(edges) == 9
    codes = np.searchsorted(edges, values, side="left")
    assert np.bincount(codes).tolist() == [100] * 10


def test_the_noise_floor_shrinks_with_the_sample():
    assert drift._noise_floor(5, 1000, 1000) == pytest.approx(4 * 0.002)
    assert drift._noise_floor(5, 4000, 4000) < drift._noise_floor(5, 1000, 1000)


def test_the_most_moved_levels_are_the_largest_contributions():
    import pandas as pd

    shares = pd.DataFrame(
        {
            "factor": ["a", "a", "a", "b"],
            "level": ["x", "y", "z", "w"],
            "psi_part": [0.01, 0.30, 0.05, 0.02],
        }
    )
    out = drift.most_moved(shares, top=2)
    assert out.loc[out["factor"] == "a", "level"].tolist() == ["y", "z"]
    assert out.loc[out["factor"] == "b", "level"].tolist() == ["w"]


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
    return frozen, outofsample.load_out_of_time(frozen)


def test_factor_psi_covers_every_rating_and_analysis_only_factor(setup):
    frozen, oot = setup
    table = drift.factor_psi(frozen, oot, n_boot=100)
    assert len(table) == 14
    assert set(table["kind"]) == {"rating", "analysis_only"}
    assert (table["psi"] >= 0).all() and (table["lower_95"] <= table["upper_95"]).all()
    assert table.loc[table["measure"] == "age", "levels"].iloc[0] == 16


def test_predicted_cost_psi_uses_ten_bins_and_the_shares_add_to_one(setup):
    frozen, oot = setup
    table, shares = drift.predicted_cost_psi(frozen, oot, n_boot=100)
    assert len(table) == 2 and (table["levels"] <= 10).all()
    assert shares.groupby(["model", "period"])["share"].sum().tolist() == pytest.approx([1.0] * 4)
    # the bins are set on 2022 train, so its shares are near one in ten where the edges are unique
    first = shares[(shares["period"] == "2022")]
    assert first["share"].max() < 0.14


def test_level_shares_add_to_one_for_each_factor(setup):
    frozen, oot = setup
    shares = drift.level_shares(frozen, oot, ["age", "region"])
    sums = shares.groupby("factor")[["share_2022", "share_2023"]].sum()
    assert sums.to_numpy() == pytest.approx(np.ones((2, 2)), abs=1e-3)
