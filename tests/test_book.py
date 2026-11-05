"""Tests for the in-force book and scenario impact (M6, issue #61)."""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import outofsample
from health_pricing.rating import book as bk
from health_pricing.rating import engine

VERSION = "m6_draft"


@pytest.fixture(scope="module")
def tariff():
    if not (engine.OUTPUTS / VERSION / engine.RELATIVITIES).exists():
        pytest.skip("run python -m health_pricing.models.finaltariff")
    return engine.load_tariff(VERSION)


@pytest.fixture(scope="module")
def modelling():
    frozen = outofsample.freeze()
    return pd.concat([frozen.prepared.train, frozen.prepared.test])


@pytest.fixture(scope="module")
def book(modelling):
    return bk.build_book(modelling)


def test_book_totals_equal_the_modelling_table_and_hold_only_cells(book, modelling):
    assert book["exposure"].sum() == pytest.approx(modelling["exposure"].sum())
    assert set(book.columns) == {*bk.KEYS, "exposure"}
    assert not book.duplicated(bk.KEYS).any()


def test_small_cells_are_merged_into_the_same_age_band_and_region(modelling):
    full = bk.build_book(modelling, min_persons=1)
    merged = bk.build_book(modelling, min_persons=10)
    assert len(merged) < len(full)
    assert merged["exposure"].sum() == pytest.approx(full["exposure"].sum())
    by_cell = lambda d: d.groupby(["age", "region"])["exposure"].sum()  # noqa: E731
    assert np.allclose(by_cell(merged), by_cell(full).reindex(by_cell(merged).index))


def test_cell_premiums_equal_the_engine(book, tariff):
    sample = book.sample(60, random_state=3)
    lower = {label: low for low, _, label in tariff.age_bands}
    premiums = bk.cell_premiums(sample, tariff)
    for index, row in sample.iterrows():
        profile = {k: (lower[row[k]] if k == "age" else row[k]) for k in bk.KEYS}
        assert premiums[index] == pytest.approx(engine.rate(profile, tariff=tariff)["premium"])


def test_zero_scenario_changes_nothing(book, tariff):
    result = bk.apply_scenario(book, bk.Scenario(), tariff)
    assert (result["cells"]["change_pct"] == 0).all()
    assert result["totals"]["change_pct"] == 0
    assert result["totals"]["cap_floor_cost"] == pytest.approx(0)


def test_base_only_change_moves_every_cell_by_the_same_percent(book, tariff):
    result = bk.apply_scenario(book, bk.Scenario(base_change=0.07), tariff)
    assert np.allclose(result["cells"]["change_pct"], 7.0)
    assert result["totals"]["change_pct"] == pytest.approx(7.0)


def test_cap_and_floor_bind_after_relativity_changes_and_the_cost_is_reported(book, tariff):
    scenario = bk.Scenario(
        base_change=0.04,
        relativity_changes={("age", "80+"): 0.10},
        cap=0.08,
        floor=0.05,
    )
    result = bk.apply_scenario(book, scenario, tariff)
    cells = result["cells"]
    assert cells["change_pct"].max() == pytest.approx(8.0)
    assert cells["change_pct"].min() == pytest.approx(5.0)
    old80 = cells[cells["age"] == "80+"]
    assert np.allclose(old80["change_pct"], 8.0)
    assert (old80["uncapped_change_pct"] > 8.0).all()
    assert result["totals"]["cells_capped"] == len(old80)
    assert result["totals"]["cells_floored"] == (cells["uncapped_change_pct"] < 5.0).sum()
    expected = (
        cells["exposure"] * cells["old_premium"] * (1 + cells["uncapped_change_pct"] / 100)
    ).sum() - (cells["exposure"] * cells["new_premium"]).sum()
    assert result["totals"]["cap_floor_cost"] == pytest.approx(expected)


def test_pound_columns_appear_with_a_scaling_and_totals_reconcile(book, tariff):
    scaled = dataclasses.replace(tariff, scaling={"gbp_per_usd_premium": 0.25})
    result = bk.apply_scenario(book, bk.Scenario(base_change=0.1), scaled)
    cells, totals = result["cells"], result["totals"]
    assert totals["new_premium_gbp"] == pytest.approx(0.25 * totals["new_premium"])
    assert np.allclose(cells["change_amount_gbp"], 0.25 * cells["change_amount"])
    unscaled = dataclasses.replace(tariff, scaling=None)
    assert "old_premium_gbp" not in bk.apply_scenario(book, bk.Scenario(), unscaled)["cells"]


def test_dislocation_covers_age_group_region_and_conditions(book, tariff):
    result = bk.apply_scenario(book, bk.Scenario(base_change=0.05), tariff)
    table = bk.dislocation(result["cells"])
    assert set(table["dimension"]) == {"age group", "region", "number of conditions"}
    assert set(table.loc[table["dimension"] == "age group", "segment"]) == set(bk.AGE_GROUPS)
    assert np.allclose(table["mean_change_pct"], 5.0)
    for dimension, part in table.groupby("dimension"):
        assert part["exposure"].sum() == pytest.approx(book["exposure"].sum())
