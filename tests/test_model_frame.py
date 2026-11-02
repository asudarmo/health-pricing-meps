"""Tests for the M3 modelling frames (issue #23)."""

from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import frame as mf

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "dbt" / "models" / "marts" / "schema.yml"


def _row(person, year, split, **overrides):
    row = {
        "DUPERSID": person, "DUID": int(person[:3]), "year": year, "split": split,
        "age": 30, "region": 1, "inscov": 1, "rthlth": 2, "mnhlth": 2,
        "OFTSMK53": "3", "PHYEXE53": "1", "HIBPDX": "0", "CHDDX": "0", "ANGIDX": "0",
        "MIDX": "0", "OHRTDX": "0", "STRKDX": "0", "CHOLDX": "0", "CANCERDX": "0",
        "ARTHDX": "0", "ASTHDX": "0", "DIABDX_M18": "0",
        "exposure": 1.0, "claim_count": 0, "claim_cost_2023_prices": 0.0,
    }  # fmt: skip
    row.update(overrides)
    return row


@pytest.fixture
def mart():
    rows = [
        _row("1001", 2022, "train", claim_count=2, claim_cost_2023_prices=300.0, region=1),
        _row("1002", 2022, "train", region=2, OFTSMK53="not_applicable", exposure=1.0),
        _row("1003", 2022, "train", region=2, OFTSMK53="not_applicable", exposure=1.0),
        _row("1004", 2022, "train", region=2, OFTSMK53="2", exposure=0.5, rthlth=None),
        _row("2001", 2022, "test", claim_count=1, claim_cost_2023_prices=80.0, region=4),
        _row("2002", 2022, "test", region=3),
        _row("3001", 2023, "out_of_time", claim_count=1, claim_cost_2023_prices=50.0),
        _row("3002", 2023, "out_of_time"),
    ]
    return pd.DataFrame(rows)


def test_train_and_test_hold_only_their_own_2022_rows_and_never_out_of_time(mart):
    frames = mf.build_frames(mart)
    assert set(frames.train["split"]) == {"train"}
    assert set(frames.test["split"]) == {"test"}
    assert set(frames.train["year"]) | set(frames.test["year"]) == {2022}
    held_back = set(mart.loc[mart["split"] == "out_of_time", "DUPERSID"])
    assert not held_back & (set(frames.train["DUPERSID"]) | set(frames.test["DUPERSID"]))
    assert not set(frames.train["DUPERSID"]) & set(frames.test["DUPERSID"])


def test_loading_from_the_database_applies_the_same_rule(mart):
    con = duckdb.connect(":memory:")
    con.register("source", mart)
    con.execute("CREATE TABLE mart_person_year AS SELECT * FROM source")
    frames = mf.load_frames(con)
    assert len(frames.train) == 4 and len(frames.test) == 2
    assert 2023 not in set(frames.train["year"]) | set(frames.test["year"])


def test_claimant_indicator_and_cost_per_claimant(mart):
    train = mf.build_frames(mart).train.set_index("DUPERSID")
    assert train.loc["1001", "claimant"] == 1
    assert train.loc["1001", "cost_per_claimant"] == 300.0
    assert train.loc["1002", "claimant"] == 0
    assert pd.isna(train.loc["1002", "cost_per_claimant"])


def test_the_reference_is_the_level_with_most_exposure_never_a_placeholder(mart):
    reference = mf.build_frames(mart).reference_levels
    # not_applicable has the most exposure (2.0) but can never be the reference
    assert reference["OFTSMK53"] == "3"
    assert reference["region"] == "2"  # exposure 2.5, against 1.0 for region 1


def test_a_tie_goes_to_the_level_that_sorts_first_numerically(mart):
    mart.loc[mart["DUPERSID"] == "1002", "age"] = 10
    mart.loc[mart["DUPERSID"] == "1003", "age"] = 9
    mart.loc[mart["DUPERSID"] == "1004", "age"] = 9
    mart.loc[mart["DUPERSID"] == "1001", "age"] = 10
    mart.loc[mart["DUPERSID"] == "1004", "exposure"] = 1.0
    assert mf.build_frames(mart).reference_levels["age"] == "9"  # 9 and 10 tie, 9 sorts first


def test_factors_are_categoricals_with_the_reference_first_and_shared_levels(mart):
    frames = mf.build_frames(mart)
    for factor in mf.FACTORS:
        assert isinstance(frames.train[factor].dtype, pd.CategoricalDtype)
        categories = list(frames.train[factor].cat.categories)
        assert categories[0] == frames.reference_levels[factor]
        assert categories == list(frames.test[factor].cat.categories)
    assert list(frames.train["region"].cat.categories) == ["2", "1", "3", "4"]
    assert "4" in list(frames.train["region"].cat.categories)  # a level seen only in test


def test_a_missing_answer_stays_null_and_is_not_a_level(mart):
    train = mf.build_frames(mart).train.set_index("DUPERSID")
    assert pd.isna(train.loc["1004", "rthlth"])
    assert train["rthlth"].cat.categories.tolist() == ["2"]


def test_the_factor_list_is_the_rating_factor_list_in_the_mart_schema():
    model = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))["models"][0]
    declared = [c["name"] for c in model["columns"] if c["meta"]["role"] == "rating_factor"]
    assert mf.FACTORS == declared


def test_summary_and_reference_tables(mart):
    frames = mf.build_frames(mart)
    summary = mf.frame_summary(frames).set_index("split")
    assert summary.loc["train", "person_years"] == 4
    assert summary.loc["train", "claimants"] == 1
    assert summary.loc["train", "cost"] == 300.0
    assert summary.loc["test", "mean_cost_per_claimant"] == 80.0
    table = mf.reference_table(frames).set_index("factor")
    assert table.loc["region", "exposure_share"] == pytest.approx(2.5 / 3.5)


def test_zero_cost_claimants_are_counted_in_the_summary(mart):
    extra = pd.DataFrame([_row("1005", 2022, "train", claim_count=1, claim_cost_2023_prices=0.0)])
    frames = mf.build_frames(pd.concat([mart, extra], ignore_index=True))
    summary = mf.frame_summary(frames).set_index("split")
    assert summary.loc["train", "zero_cost_claimants"] == 1
    assert summary.loc["test", "zero_cost_claimants"] == 0


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


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_row_counts_equal_the_mart_counts_for_2022():
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        expected = dict(
            con.execute(
                "SELECT split, COUNT(*) FROM mart_person_year WHERE year = 2022 GROUP BY split"
            ).fetchall()
        )
        frames = mf.load_frames(con)
    finally:
        con.close()
    assert len(frames.train) == expected["train"]
    assert len(frames.test) == expected["test"]
    assert set(frames.train["split"]) == {"train"} and set(frames.test["split"]) == {"test"}
    for placeholder in mf.NOT_REFERENCE:
        assert placeholder not in frames.reference_levels.values()


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_metrics_on_the_real_frames_reconcile_and_the_baseline_does_not_rank():
    import numpy as np

    from health_pricing.models import metrics as mm

    frames = mf.load_frames()
    test = frames.test
    baseline = mm.baseline_predictions(frames.train, test)
    assert mm.gini(test["cost"], baseline, test["exposure"]) == pytest.approx(0.0, abs=1e-12)
    lift = mm.lift_table(test["cost"], baseline, test["exposure"])
    assert lift["person_years"].sum() == len(test)
    assert lift["actual"].sum() == pytest.approx(test["cost"].sum())
    assert lift["exposure"].tolist() == pytest.approx([test["exposure"].sum() / 10] * 10, rel=0.02)
    shifted = baseline * np.where(test["age"].astype(int) >= 50, 1.5, 0.8)
    double = mm.double_lift_table(test["cost"], baseline, shifted, test["exposure"])
    assert double["actual"].sum() == pytest.approx(test["cost"].sum())
    assert double["predicted_a"].sum() == pytest.approx(baseline.sum())
