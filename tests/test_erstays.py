"""Tests for the ER-originated stays sensitivity (M5, issue #49)."""

import duckdb
import numpy as np
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import erstays, outofsample


def toy_mart():
    return pd.DataFrame(
        {
            "age": [5, 30, 30, 50, 70, 70],
            "claim_count": [1, 0, 2, 0, 3, 0],
            "claim_cost_2023_prices": [100.0, 0.0, 400.0, 0.0, 900.0, 0.0],
            "er_stay_count": [0, 1, 0, 0, 1, 1],
            "er_stay_cost_2023_prices": [0.0, 50.0, 0.0, 0.0, 300.0, 200.0],
        }
    )


def test_broadening_adds_the_er_stay_count_and_cost_to_the_base():
    out = erstays.broaden(toy_mart())
    assert out["claim_cost_2023_prices"].tolist() == [100.0, 50.0, 400.0, 0.0, 1200.0, 200.0]
    assert out["claim_count"].tolist() == [1, 1, 2, 0, 4, 1]


def test_added_by_age_group_counts_cost_and_new_claimants():
    table = erstays.added_by_age_group(toy_mart()).set_index("age_group")
    assert table.loc["All", "er_stay_cost"] == pytest.approx(550.0)
    assert table.loc["All", "cost_added_pct"] == pytest.approx(100 * 550 / 1400)
    assert table.loc["All", "claimants_added"] == 2  # the 30-year-old and the second 70-year-old
    assert table.loc["65+", "claimants_added"] == 1
    assert table.loc["18-39", "cost_added_pct"] == pytest.approx(100 * 50 / 400)
    assert list(table.index) == ["Children", "18-39", "40-64", "65+", "All"]


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
def sens():
    if not _built():
        pytest.skip("run the load script and dbt build")
    base = outofsample.freeze()
    return erstays.build(base, outofsample.load_out_of_time(base))


def test_the_broadened_cost_is_the_base_cost_plus_the_er_stay_cost_for_every_person_year(sens):
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        expected = con.execute(
            "SELECT DUPERSID, year, claim_cost_2023_prices + er_stay_cost_2023_prices AS total, "
            "claim_count + er_stay_count AS count FROM mart_person_year "
            "WHERE year IN (2022, 2023) AND split IN ('train', 'test', 'out_of_time')"
        ).fetchdf()
    finally:
        con.close()
    for mart in (sens.mart_2022, sens.mart_2023):
        broad = erstays.broaden(mart).merge(expected, on=["DUPERSID", "year"], validate="1:1")
        assert np.allclose(broad["claim_cost_2023_prices"], broad["total"])
        assert (broad["claim_count"] == broad["count"]).all()
        assert (broad["claim_cost_2023_prices"] >= mart["claim_cost_2023_prices"].to_numpy()).all()


def test_the_broadened_2023_frame_has_the_same_rows_and_more_cost(sens):
    assert len(sens.broad_oot.frame) == len(sens.base_oot.frame)
    assert set(sens.broad_oot.frame["DUPERSID"]) == set(sens.base_oot.frame["DUPERSID"])
    assert sens.broad_oot.frame["cost"].sum() > sens.base_oot.frame["cost"].sum()


def test_the_base_model_a_e_rises_by_the_added_cost_share_and_the_ranking_holds(sens):
    overall, ages, gini = erstays.score_against_broadened(sens, 1.019, n_boot=50)
    technical = overall[overall["model"] == outofsample.TECHNICAL].set_index("definition")["a_e"]
    added = erstays.added_by_age_group(sens.mart_2023).set_index("age_group").loc["All"]
    expected = technical["Base definition"] * (1 + added["cost_added_pct"] / 100)
    assert technical["With ER-originated stays"] == pytest.approx(expected, rel=1e-6)
    assert len(ages) == 2 * 2 * 4
    table = gini[gini["candidate"] == outofsample.TECHNICAL].set_index("definition")["gini"]
    assert table["With ER-originated stays"] > 0.3


def test_the_refit_comparison_covers_every_level_and_the_factor_ranking(sens):
    comparison = erstays.relativity_comparison(sens)
    assert set(comparison["part"]) == {"frequency", "severity", "combined"}
    assert {"relativity_base", "relativity_broad", "ratio"} <= set(comparison.columns)
    ranking = erstays.factor_ranking(comparison)
    assert sorted(ranking["rank_base"]) == list(range(1, len(ranking) + 1))
    curve = erstays.age_curves(sens)
    assert curve.loc[curve["age"] == 67, "ratio"].iloc[0] == pytest.approx(1.0)
