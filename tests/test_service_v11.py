"""Tests for the additive v1.1 service fields: /model, scenario additions, typed responses."""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from health_pricing.rating import engine, flags
from health_pricing.service import app as service

FOLDER = engine.OUTPUTS / "v1"
SCENARIO = {
    "base_change": 0.04,
    "relativity_changes": [{"factor": "age", "level": "80+", "change": 0.1}],
    "cap": 0.12,
    "floor": 0.0,
}


@pytest.fixture(scope="module")
def client():
    return TestClient(service.app)


@pytest.fixture(scope="module")
def model(client):
    return client.get("/model").json()


@pytest.fixture(scope="module")
def impact(client):
    return client.post("/scenario-impact", json=SCENARIO).json()


def test_model_identity_and_data_years(model):
    assert (model["id"], model["date"]) == ("v1", "2026-11-05")
    assert model["description"].startswith("v1:")
    assert model["data_years"] == {
        "fit": 2022,
        "out_of_time": 2023,
        "cost_basis": "2023 prices, PMI scope",
    }


def test_model_trend_assumptions(model):
    assert model["trend_assumptions"]["forecast_trend"] == 1.019
    assert model["trend_assumptions"]["rebase"] == 1.06


def test_model_permitted_factors_have_levels_and_labels(model):
    relativities = pd.read_csv(FOLDER / "relativities.csv", dtype={"level": str})
    factors = {f["factor"]: f for f in model["permitted_rating_factors"]}
    assert list(factors) == [
        "age",
        "region",
        "HIBPDX",
        "CHDDX",
        "CANCERDX",
        "ARTHDX",
        "ASTHDX",
        "CHOLDX",
        "OHRTDX",
    ]
    for name, item in factors.items():
        assert item["label"]
        assert [x["level"] for x in item["levels"]] == list(
            relativities.loc[relativities["factor"] == name, "level"]
        )
        assert all(x["label"] for x in item["levels"])
    assert {x["level"]: x["label"] for x in factors["region"]["levels"]}["3"] == "South"


def test_model_headline_ae_is_the_overall_row_of_the_latest_period(model):
    table = pd.read_csv(FOLDER / "ae_table.csv")
    row = table[(table["factor"] == "all") & (table["period"] == "2023 out-of-time")].iloc[0]
    headline = model["headline_ae"]
    assert headline["period"] == "2023 out-of-time"
    assert headline["a_e"] == pytest.approx(row["actual"] / row["expected"])
    assert headline["lower_95"] < headline["a_e"] < headline["upper_95"]


def test_model_flags_match_the_recalibration_rule_on_the_published_tables(model):
    intervals = pd.read_csv(FOLDER / "ae_intervals.csv", dtype={"level": str})
    table = pd.read_csv(FOLDER / "ae_table.csv", dtype={"level": str})
    table = table[table["period"] == "2023 out-of-time"].set_index(["factor", "level"])
    # the intervals sit on the published A/E
    for row in intervals.itertuples():
        published = table.loc[(row.factor, row.level)]
        assert row.a_e == pytest.approx(published["actual"] / published["expected"])
    expected = {}
    for r in intervals[intervals["enough_claimants"]].itertuples():
        gap = r.lower_95 > 1 or r.upper_95 < 1
        off = r.relative_lower_95 > 1 or r.relative_upper_95 < 1
        if gap or off:
            segment = "all" if r.factor == "all" else f"{r.factor} {r.level}"
            expected[segment] = "change in shape" if off else "level shift"
    got = {f["segment"]: f["gap_type"] for f in model["recalibration_flags"]}
    assert got == expected and got
    assert set(got.values()) <= {"level shift", "change in shape"}
    assert model["recalibration_flags"] == flags.segment_flags(intervals)
    assert all(f["note"] and f["exposure"] > 0 for f in model["recalibration_flags"])


def test_scenario_histogram_has_fixed_edges_and_the_book_exposure(impact):
    edges = impact["histogram_edges_pct"]
    assert edges == sorted(edges) and len(edges) == 11
    buckets = impact["histogram"]
    assert len(buckets) == len(edges) + 1
    assert [b["bucket_low"] for b in buckets] == [None, *edges]
    assert [b["bucket_high"] for b in buckets] == [*edges, None]
    assert sum(b["exposure"] for b in buckets) == pytest.approx(impact["totals"]["exposure"])
    assert buckets[0]["exposure"] == 0  # no cell falls more than 20 percent
    # +4 percent for most cells lands in [2.5, 5)
    assert max(buckets, key=lambda b: b["exposure"])["bucket_low"] == 2.5


def test_projected_ae_is_actual_over_expected_after_the_change(client, impact):
    table = pd.read_csv(FOLDER / "ae_table.csv")
    row = table[(table["factor"] == "all") & (table["period"] == "2023 out-of-time")].iloc[0]
    ratio = impact["totals"]["new_premium"] / impact["totals"]["old_premium"]
    assert impact["projected_ae"] == pytest.approx(row["actual"] / (row["expected"] * ratio))
    unchanged = client.post("/scenario-impact", json={}).json()
    assert unchanged["projected_ae"] == pytest.approx(row["actual"] / row["expected"])


def test_exposure_capped_and_floored_are_life_years_of_the_counted_cells(client, impact):
    totals = impact["totals"]
    cells = pd.DataFrame(
        client.post("/scenario-impact", json={**SCENARIO, "include_cells": True}).json()["cells"]
    )
    over = cells[cells["uncapped_change_pct"] > 12 + 1e-9]
    assert totals["cells_capped"] == len(over) > 0
    assert totals["exposure_capped"] == pytest.approx(over["exposure"].sum())
    assert totals["exposure_floored"] == 0
    floored = client.post("/scenario-impact", json={"base_change": -0.1, "floor": -0.05}).json()
    assert floored["totals"]["cells_floored"] > 0
    assert floored["totals"]["exposure_floored"] == pytest.approx(floored["totals"]["exposure"])


def test_existing_scenario_fields_are_unchanged(client, impact):
    published = pd.read_csv(FOLDER / "scenario_example_totals.csv").iloc[0]
    # the published example is a different scenario, so compare only the keys and a no-change run
    assert set(published.index) <= set(impact["totals"])
    assert {"model_version", "totals", "dislocation"} <= set(impact)
    assert "cells" not in impact
    zero = client.post("/scenario-impact", json={}).json()
    assert zero["totals"]["change_pct"] == pytest.approx(0)
    assert zero["totals"]["cells_capped"] == 0


def test_openapi_shows_the_full_response_shapes():
    schema = service.app.openapi()
    components = schema["components"]["schemas"]
    for path, name in (
        ("/model", "ModelResponse"),
        ("/relativities", "RelativitiesResponse"),
        ("/monitoring", "MonitoringResponse"),
    ):
        ref = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert ref["$ref"].endswith(name)
    post = schema["paths"]["/scenario-impact"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert post["$ref"].endswith("ScenarioResponse")
    assert {"histogram", "projected_ae"} <= set(components["ScenarioResponse"]["properties"])
    assert {"exposure_capped", "exposure_floored", "cells_capped"} <= set(
        components["Totals"]["properties"]
    )
    assert "recalibration_flags" in components["ModelResponse"]["properties"]
