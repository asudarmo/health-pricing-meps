"""Tests for the level evidence and grouping (issue #26)."""

import duckdb
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import frame as mf
from health_pricing.models import levels

BASE = {
    "region": 1, "inscov": 1, "rthlth": 2, "mnhlth": 2, "OFTSMK53": "3", "PHYEXE53": "1",
    "HIBPDX": "0", "CHDDX": "0", "ANGIDX": "0", "MIDX": "0", "OHRTDX": "0", "STRKDX": "0",
    "CHOLDX": "0", "CANCERDX": "0", "ARTHDX": "0", "ASTHDX": "0", "DIABDX_M18": "0",
}  # fmt: skip


def _mart(rows):
    """rows: (person, split, age, exposure, claim_count, overrides)."""
    data = []
    for i, (split, age, exposure, claims, overrides) in enumerate(rows):
        row = {
            "DUPERSID": f"p{i}", "DUID": i, "year": 2022, "split": split, "age": age,
            "exposure": exposure, "claim_count": claims,
            "claim_cost_2023_prices": 100.0 * claims, **BASE,
        }  # fmt: skip
        row.update(overrides)
        data.append(row)
    return pd.DataFrame(data)


@pytest.fixture(autouse=True)
def small_threshold(monkeypatch):
    monkeypatch.setattr(levels, "THIN_CLAIMANTS", 2)


@pytest.fixture
def frames():
    rows = []
    # adults: region 1 is the biggest level, region 2 has only one claimant, so it is thin
    for i in range(6):
        rows.append(("train", 40 + i, 1.0, 1, {}))
    rows.append(("train", 50, 1.0, 1, {"region": 2}))
    rows.append(("train", 51, 0.5, 0, {"region": 2}))
    # a child on the adult questions, and an adult who refused
    rows.append(("train", 10, 1.0, 1, {"OFTSMK53": "not_applicable", "HIBPDX": "not_applicable"}))
    rows.append(("train", 45, 1.0, 0, {"OFTSMK53": None, "HIBPDX": None}))
    # unknown, with enough claimants for smoking to keep it, and for the flag to be thin
    rows.append(("train", 80, 0.25, 2, {"OFTSMK53": "unknown", "HIBPDX": "unknown"}))
    rows.append(("train", 81, 0.25, 1, {"OFTSMK53": "unknown", "HIBPDX": "unknown"}))
    rows.append(("test", 46, 1.0, 1, {"region": 3}))  # a level only seen in test
    return mf.build_frames(_mart(rows))


def test_age_labels_at_the_band_edges():
    bands = levels.AGE_BANDS["five_year"]
    assert levels.age_label(4, bands) == "00-04"
    assert levels.age_label(5, bands) == "05-14"
    assert levels.age_label(17, bands) == "15-17"
    assert levels.age_label(18, bands) == "18-24"
    assert levels.age_label(85, bands) == "80+"
    assert levels.age_label(84, levels.AGE_BANDS["ten_year"]) == "75+"
    with pytest.raises(ValueError):
        levels.age_label(90, bands)


def test_both_age_proposals_cover_every_age_exactly_once():
    for bands in levels.AGE_BANDS.values():
        covered = [age for low, high in bands for age in range(low, high + 1)]
        assert covered == list(range(0, 86))


def test_level_evidence_counts_and_flags_thin_levels(frames):
    table = levels.level_evidence(frames.train, ["region", "OFTSMK53"]).set_index(
        ["factor", "level"]
    )
    region_two = table.loc[("region", "2")]
    assert (region_two["person_years"], region_two["claimants"]) == (2, 1)
    assert bool(region_two["thin"]) is True  # fewer than 2 claimants
    assert bool(table.loc[("region", "1"), "thin"]) is False
    assert table.loc[("OFTSMK53", "missing"), "person_years"] == 1
    # real answers first, then the placeholders
    assert levels.level_evidence(frames.train, ["OFTSMK53"])["level"].tolist() == [
        "3", "missing", "not_applicable", "unknown",
    ]  # fmt: skip


def test_age_band_table_totals_equal_the_frame(frames):
    table = levels.age_band_table(frames.train, levels.AGE_BANDS["ten_year"])
    assert table["person_years"].sum() == len(frames.train)
    assert table["claimants"].sum() == frames.train["claimant"].sum()
    assert table["exposure"].sum() == pytest.approx(frames.train["exposure"].sum())


def test_placeholders_and_thin_levels_merge_into_the_reference(frames):
    grouping = levels.build_grouping(frames, levels.AGE_BANDS["ten_year"])
    smoking = grouping.mapping["OFTSMK53"]
    assert grouping.reference["OFTSMK53"] == "3"
    assert smoking["not_applicable"] == "3"  # a child on an adult question
    assert smoking["missing"] == "3"  # a refused answer
    assert smoking["unknown"] == "unknown"  # kept as a control, it has 3 claimants
    flag = grouping.mapping["HIBPDX"]
    assert flag["unknown"] == "0"  # merges into the reference for a condition flag
    assert flag["not_applicable"] == "0" and flag["missing"] == "0"
    assert grouping.mapping["region"]["2"] == "1"  # a thin real level merges into the reference
    assert grouping.mapping["region"]["3"] == "1"  # seen only in test, so no train claimants


def test_unknown_is_not_kept_when_it_is_thin_even_for_smoking(frames, monkeypatch):
    monkeypatch.setattr(levels, "THIN_CLAIMANTS", 4)
    grouping = levels.build_grouping(frames, levels.AGE_BANDS["ten_year"])
    assert grouping.mapping["OFTSMK53"]["unknown"] == "3"


def test_the_age_reference_is_the_band_with_the_most_exposure(frames):
    grouping = levels.build_grouping(frames, levels.AGE_BANDS["ten_year"])
    assert grouping.reference["age"] == "35-44"
    assert grouping.mapping["age"]["44"] == "35-44" and grouping.mapping["age"]["45"] == "45-54"


def test_apply_grouping_recodes_with_the_reference_first_and_keeps_every_row(frames):
    grouping = levels.build_grouping(frames, levels.AGE_BANDS["ten_year"])
    grouped = levels.apply_grouping(frames, grouping)
    assert len(grouped.train) == len(frames.train) and len(grouped.test) == len(frames.test)
    assert grouped.train["exposure"].sum() == frames.train["exposure"].sum()
    for factor in mf.FACTORS:
        categories = list(grouped.train[factor].cat.categories)
        assert categories[0] == grouping.reference[factor]
        assert categories == list(grouped.test[factor].cat.categories)
        assert grouped.train[factor].notna().all()  # no null survives
    assert list(grouped.train["OFTSMK53"].cat.categories) == ["3", "unknown"]
    assert grouped.reference_levels == grouping.reference


def test_a_level_with_no_group_raises_instead_of_being_dropped(frames):
    grouping = levels.build_grouping(frames, levels.AGE_BANDS["ten_year"])
    del grouping.mapping["region"]["3"]
    with pytest.raises(KeyError):
        levels.apply_grouping(frames, grouping)


def test_the_grouping_summary_adds_up_to_the_train_frame(frames):
    grouping = levels.build_grouping(frames, levels.AGE_BANDS["ten_year"])
    summary = levels.grouping_summary(frames, grouping)
    for factor, rows in summary.groupby("factor"):
        assert rows["person_years"].sum() == len(frames.train), factor
        assert rows["claimants"].sum() == frames.train["claimant"].sum(), factor
        assert rows["reference"].sum() == 1, factor
    row = summary[(summary["factor"] == "OFTSMK53") & summary["reference"]].iloc[0]
    assert row["levels_merged"] == "3, missing, not_applicable"


def test_the_map_table_has_one_group_per_factor_and_level(frames):
    table = levels.build_grouping(frames, levels.AGE_BANDS["five_year"]).table()
    assert not table.duplicated(["factor", "level"]).any()
    assert set(table["factor"]) == set(mf.FACTORS)
    flagged = table[table["reference"]].groupby("factor")["group"].nunique()
    assert (flagged == 1).all() and set(flagged.index) == set(mf.FACTORS)


def test_the_decided_grouping_uses_five_year_bands(frames):
    decided = levels.decided_grouping(frames)
    assert decided.mapping == levels.build_grouping(frames, levels.AGE_BANDS["five_year"]).mapping
    assert decided.mapping["age"]["44"] == "40-44"


def test_the_saved_map_round_trips(frames, tmp_path):
    grouping = levels.decided_grouping(frames)
    path = levels.save_grouping(grouping, tmp_path / "sub" / "level_grouping.csv")
    saved = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert list(saved.columns) == ["factor", "level", "group", "reference"]
    assert len(saved) == len(grouping.table())
    assert saved["group"].tolist() == grouping.table()["group"].tolist()


def test_the_presentation_age_reference_is_the_busiest_adult_band(frames):
    grouping = levels.decided_grouping(frames)
    train = frames.train.assign(age=frames.train["age"].astype(int))
    # a child band becomes the technical reference, and the adult choice must ignore it
    child = train.iloc[:1].assign(age=7, exposure=100.0)
    child_frames = mf.Frames(pd.concat([train, child], ignore_index=True), frames.test, {})
    child_grouping = levels.build_grouping(child_frames, levels.AGE_BANDS["five_year"])
    assert child_grouping.reference["age"] == "05-14"
    adult = levels.presentation_age_reference(child_frames, child_grouping)
    assert adult == levels.presentation_age_reference(frames, grouping)
    assert adult[:2] != "05" and int(adult[:2]) >= 18


def test_inscov_table_shares_add_to_one(frames):
    table = levels.inscov_table(frames.train)
    assert table["person_years_share"].sum() == pytest.approx(1)
    assert table["cost_share"].sum() == pytest.approx(1)
    assert table["claimants"].sum() == frames.train["claimant"].sum()


def test_unknown_rule_table_applies_the_two_percent_test():
    base = {"age": 30, "left_survey_early": False, "exposure": 1.0, "cost": 100.0}
    rows = [{**base, "claim_count": 1, "OFTSMK53": "3", "HIBPDX": "0"} for _ in range(8)]
    # each leaver is unknown on one variable and a placeholder on the other, so it counts only once
    for variable, other, cost in (("OFTSMK53", "HIBPDX", 5000.0), ("HIBPDX", "OFTSMK53", 51.0)):
        leaver = {**base, "age": 80, "exposure": 0.5, "cost": cost, "claim_count": 1}
        rows.append({**leaver, variable: "unknown", other: "not_applicable"})
    table = levels.unknown_rule_table(pd.DataFrame(rows), ["OFTSMK53", "HIBPDX"])
    table = table.set_index("variable")
    assert table.loc["OFTSMK53", "exceeds_limit"] and table.loc["OFTSMK53", "kept_as_control"]
    assert not table.loc["HIBPDX", "exceeds_limit"]
    assert not table.loc["HIBPDX", "kept_as_control"]


# --- The real mart ---------------------------------------------------------------------------


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
@pytest.mark.parametrize("option", ["five_year", "ten_year"])
def test_every_value_in_the_whole_mart_maps_to_exactly_one_group(option, monkeypatch):
    monkeypatch.setattr(levels, "THIN_CLAIMANTS", 30)  # the real threshold, not the test one
    frames = mf.load_frames()
    grouping = levels.build_grouping(frames, levels.AGE_BANDS[option])
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        for factor in mf.FACTORS:
            values = con.execute(f"SELECT DISTINCT {factor} FROM mart_person_year").fetchall()
            observed = {levels.MISSING if v is None else str(v) for (v,) in values}
            mapped = grouping.mapping[factor]
            assert observed <= set(mapped), (factor, sorted(observed - set(mapped)))
    finally:
        con.close()
    table = grouping.table()
    assert not table.duplicated(["factor", "level"]).any()
    regrouped = levels.apply_grouping(frames, grouping)
    assert len(regrouped.train) == len(frames.train)


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_the_kept_unknown_levels_are_exactly_those_that_fail_the_two_percent_test():
    table = levels.unknown_rule_table()
    assert set(table.loc[table["exceeds_limit"], "variable"]) == set(levels.KEEP_UNKNOWN)
    assert (table["exceeds_limit"] == table["kept_as_control"]).all()


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_the_real_decided_grouping_has_the_approved_references():
    grouping = levels.decided_grouping(mf.load_frames())
    assert len(grouping.mapping["age"]) == 86 and grouping.reference["age"] == "05-14"
    assert len(set(grouping.mapping["age"].values())) == 16
    assert levels.presentation_age_reference(mf.load_frames(), grouping) == "65-69"
