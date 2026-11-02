"""Tests for the leakage tables on the `unknown` level (issue #25), on hand-made rows."""

import duckdb
import pandas as pd
import pytest

from health_pricing.models import leakage

VARIABLES = ["OFTSMK53", "HIBPDX"]


@pytest.fixture
def adults():
    rows = [
        # age, left, exposure, claims, cost, OFTSMK53, HIBPDX
        (40, False, 1.0, 2, 100.0, "3", "0"),
        (50, False, 1.0, 0, 0.0, "3", "1"),
        (70, True, 0.5, 1, 300.0, "unknown", "unknown"),
        (18, False, 1.0, 0, 0.0, "1", "unknown"),
        (60, False, 1.0, 1, 200.0, "2", "0"),
        (30, False, 1.0, 0, 0.0, None, None),  # refused: neither unknown nor answered
    ]
    columns = ["age", "left_survey_early", "exposure", "claim_count", "cost", *VARIABLES]
    return pd.DataFrame(rows, columns=columns)


def test_unknown_against_answered_for_the_smoking_question(adults):
    table = leakage.unknown_level_table(adults, VARIABLES).set_index(["variable", "group"])
    unknown = table.loc[("OFTSMK53", "unknown")]
    assert unknown["person_years"] == 1
    assert unknown["mean_age"] == 70
    assert unknown["share_under_25"] == 0
    assert unknown["share_left_survey_early"] == 1.0
    assert unknown["share_exposure_under_1"] == 1.0
    assert unknown["mean_exposure"] == 0.5
    assert unknown["claimant_rate"] == 1.0
    assert unknown["mean_cost_per_claimant"] == 300.0
    assert unknown["cost_per_exposure_year"] == pytest.approx(600.0)


def test_answered_adults_exclude_unknown_and_refused(adults):
    answered = leakage.unknown_level_table(adults, VARIABLES).set_index(["variable", "group"])
    row = answered.loc[("OFTSMK53", "answered")]
    assert row["person_years"] == 4  # the refused row is in neither group
    assert row["share_under_25"] == 0.25
    assert row["share_left_survey_early"] == 0
    assert row["claimant_rate"] == 0.5
    assert row["mean_cost_per_claimant"] == 150.0
    assert row["cost_per_exposure_year"] == pytest.approx(300 / 4)


def test_each_variable_gets_its_own_groups(adults):
    table = leakage.unknown_level_table(adults, VARIABLES).set_index(["variable", "group"])
    row = table.loc[("HIBPDX", "unknown")]
    assert row["person_years"] == 2
    assert row["mean_age"] == 44
    assert row["share_left_survey_early"] == 0.5
    assert row["cost_per_exposure_year"] == pytest.approx(300 / 1.5)


def test_the_leaver_table_reads_the_other_direction(adults):
    table = leakage.unknown_by_leaver_table(adults, VARIABLES).set_index("variable")
    smoking = table.loc["OFTSMK53"]
    assert smoking["leavers"] == 1
    assert smoking["leavers_unknown_share"] == 1.0
    assert smoking["stayers_unknown_share"] == 0.0
    flag = table.loc["HIBPDX"]
    assert flag["leavers_unknown_share"] == 1.0
    assert flag["stayers_unknown_share"] == pytest.approx(0.25)


def test_the_merge_effect_shows_how_far_unknown_would_move_the_reference_cost(adults):
    table = leakage.merge_effect_table(adults, VARIABLES).set_index("variable")
    row = table.loc["OFTSMK53"]
    assert row["reference_level"] == "3"
    assert row["unknown_share_of_reference_exposure"] == pytest.approx(0.5 / 2)
    assert row["reference_cost_per_exposure_year"] == pytest.approx(50.0)
    assert row["cost_after_merge"] == pytest.approx(400 / 2.5)
    assert row["change_after_merge"] == pytest.approx(160 / 50 - 1)


def test_all_thirteen_variables_with_an_unknown_level_are_covered():
    assert len(leakage.UNKNOWN_VARIABLES) == 13
    assert leakage.UNKNOWN_VARIABLES[:2] == ["OFTSMK53", "PHYEXE53"]
    assert "ASTHDX" in leakage.UNKNOWN_VARIABLES and "DIABDX_M18" in leakage.UNKNOWN_VARIABLES


def test_the_loader_takes_only_2022_train_adults():
    con = duckdb.connect(":memory:")
    columns = ", ".join(f"'x' AS {v}" for v in leakage.UNKNOWN_VARIABLES)
    con.execute(
        "CREATE TABLE mart_person_year AS "
        f"SELECT * FROM (VALUES (2022, 'train', 30), (2022, 'train', 17), (2022, 'train', 18), (2022, 'test', 40), "
        f"(2023, 'out_of_time', 40)) AS t(year, split, age), "
        f"(SELECT {columns}, true AS left_survey_early, 1.0 AS exposure, 1 AS claim_count, "
        f"5.0 AS claim_cost_2023_prices)"
    )
    frame = leakage.load_leakage_frame(con)
    assert sorted(frame["age"]) == [18, 30]  # 18 is an adult, 17 is not
    assert {"left_survey_early", "exposure", "claim_count", "cost"} <= set(frame.columns)


def test_not_applicable_is_never_an_answer_and_never_unknown():
    frame = pd.DataFrame(
        {
            "age": [40, 50], "left_survey_early": [False, False], "exposure": [1.0, 1.0],
            "claim_count": [0, 0], "cost": [0.0, 0.0], "OFTSMK53": ["3", "not_applicable"],
        }
    )  # fmt: skip
    table = leakage.unknown_level_table(frame, ["OFTSMK53"]).set_index("group")
    assert table.loc["answered", "person_years"] == 1
    assert table.loc["unknown", "person_years"] == 0


def test_the_part_year_share_counts_exposure_below_one_not_at_one():
    frame = pd.DataFrame(
        {
            "age": [40, 50, 60], "left_survey_early": [False, False, False],
            "exposure": [1.0, 0.99, 0.5], "claim_count": [0, 0, 0], "cost": [0.0, 0.0, 0.0],
            "OFTSMK53": ["3", "3", "3"],
        }
    )  # fmt: skip
    table = leakage.unknown_level_table(frame, ["OFTSMK53"]).set_index("group")
    assert table.loc["answered", "share_exposure_under_1"] == pytest.approx(2 / 3)
