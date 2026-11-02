"""Tests for the frozen final model and the 2023 scoring frame (M5, issue #42)."""

import duckdb
import numpy as np
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import frame as mf
from health_pricing.models import glm, large_claims, levels, outofsample


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


pytestmark = pytest.mark.skipif(not _built(), reason="run the load script and dbt build")


@pytest.fixture(scope="module")
def frozen():
    return outofsample.freeze()


@pytest.fixture(scope="module")
def oot(frozen):
    return outofsample.load_out_of_time(frozen)


def test_the_frozen_model_reproduces_the_saved_m3_scores(frozen):
    spline_frames = frozen.final_tariff.frames["spline"]
    technical = {
        "train": (spline_frames.train, frozen.technical(spline_frames.train)),
        "test": (spline_frames.test, frozen.technical(spline_frames.test)),
    }
    scores = glm.candidate_scores("technical", frozen.spline.model.parameters, technical)
    age = pd.read_csv(glm.SCORES_DIR / "age_curve_comparison.csv")
    saved = age[(age["spline"] == "spline with 4 df") & (age["model"] == "spline")].iloc[0]
    test = scores[scores["split"] == "test"].iloc[0]
    assert test["tweedie_deviance"] == pytest.approx(saved["test_deviance"], rel=1e-6)
    assert test["parameters"] == saved["parameters"] == 64
    # the base rate is rebalanced, so train predicted cost equals train actual cost
    train = scores[scores["split"] == "train"].iloc[0]
    assert train["a_e"] == pytest.approx(1.0, abs=1e-9)

    prepared = frozen.prepared
    tariff = {
        "train": (prepared.train, frozen.tariff(prepared.train)),
        "test": (prepared.test, frozen.tariff(prepared.test)),
    }
    tariff_scores = glm.candidate_scores("tariff", frozen.final_tariff.tariff.parameters, tariff)
    final = pd.read_csv(glm.SCORES_DIR / "final_scores.csv").set_index(["candidate", "split"])
    row = tariff_scores[tariff_scores["split"] == "test"].iloc[0]
    assert row["tweedie_deviance"] == pytest.approx(
        final.loc[("final_tariff", "test"), "tweedie_deviance"], rel=1e-6
    )
    assert row["gini"] == pytest.approx(final.loc[("final_tariff", "test"), "gini"], abs=1e-6)
    assert row["parameters"] == 26


def test_the_2023_frame_matches_the_mart_and_every_level_maps_to_a_group(frozen, oot):
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        total = con.execute(
            "SELECT COUNT(*), SUM(exposure), SUM(claim_cost_2023_prices) FROM mart_person_year "
            "WHERE year = 2023 AND split = 'out_of_time'"
        ).fetchone()
    finally:
        con.close()
    assert len(oot.frame) == total[0]
    assert oot.frame["exposure"].sum() == pytest.approx(total[1])
    assert oot.frame["cost"].sum() == pytest.approx(total[2])
    assert oot.new_levels.empty  # no level in 2023 is new to the grouping
    for factor in mf.FACTORS:
        categories = list(frozen.prepared.train[factor].cat.categories)
        assert list(oot.frame[factor].cat.categories) == categories
        assert oot.frame[factor].notna().all()
    assert set(oot.frame["split"]) == {"out_of_time"}


def test_costs_are_capped_per_person_year_and_the_claimant_indicator_is_positive_cost(oot):
    frame = oot.frame
    assert frame["capped_cost"].max() <= large_claims.LARGE_CLAIM_CAP
    assert (frame["capped_cost"] == np.minimum(frame["cost"], large_claims.LARGE_CLAIM_CAP)).all()
    assert (frame["claimant"] == (frame["capped_cost"] > 0)).all()


def test_both_models_predict_a_positive_finite_cost_for_every_2023_person_year(frozen, oot):
    for name, predicted in frozen.predictions(oot.spline_frame).items():
        assert len(predicted) == len(oot.frame), name
        assert np.isfinite(predicted).all() and (predicted > 0).all(), name


def test_the_2023_rows_are_not_used_to_fit(frozen, oot):
    # the fitted models hold only train rows, so a different 2023 frame cannot change them
    before = frozen.final_tariff.tariff.result.params.copy()
    outofsample.group_out_of_time(frozen, outofsample._load_mart())
    assert frozen.final_tariff.tariff.result.params.equals(before)
    assert frozen.spline.model.frequency.nobs == len(frozen.prepared.train)


def test_a_level_new_in_2023_goes_to_the_reference_and_is_reported(frozen):
    mart = outofsample._load_mart().iloc[:200].copy()
    mart["region"] = mart["region"].astype(object)
    mart.loc[mart.index[:3], "region"] = 9
    out = outofsample.group_out_of_time(frozen, mart)
    reported = out.new_levels[out.new_levels["factor"] == "region"].iloc[0]
    assert reported["level"] == "9" and reported["rows"] == 3
    assert reported["treated_as"] == frozen.grouping.reference["region"]
    assert (out.frame.loc[:2, "region"] == frozen.grouping.reference["region"]).all()


def test_the_period_summary_puts_2023_next_to_2022(frozen, oot):
    table = outofsample.period_summary(frozen, oot).set_index("period")
    assert list(table.index) == ["2022 train", "2022 test", "2023"]
    assert table.loc["2023", "person_years"] == len(oot.frame)
    assert table.loc["2022 train", "claimants"] == int(
        (frozen.prepared.train["capped_cost"] > 0).sum()
    )
    assert table.loc["2022 train", "cost_per_exposure_year_vs_2022_train"] == 0
    assert table.loc["2023", "cost_per_exposure_year_vs_2022_train"] > 0
    excess = table.loc["2023", "share_of_cost_above_cap"]
    cost = oot.frame["cost"].sum()
    assert excess == pytest.approx((cost - oot.frame["capped_cost"].sum()) / cost)
    assert table.loc["2022 train", "excess_load"] == pytest.approx(0.0647, abs=5e-4)


def test_the_grouping_is_the_m3_grouping(frozen):
    assert frozen.grouping.mapping == levels.decided_grouping(frozen.raw).mapping
