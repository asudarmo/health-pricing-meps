"""Tests for the smoking relativity check (issue #40)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import factors, glm, smoking
from health_pricing.models import frame as mf


def test_band_starts_and_broad_groups():
    assert smoking.band_start("05-14") == 5 and smoking.band_start("80+") == 80
    assert smoking.broad_group("00-04") is None
    assert smoking.broad_group("15-17") is None
    assert smoking.broad_group("18-24") == "18-39"
    assert smoking.broad_group("35-39") == "18-39"
    assert smoking.broad_group("40-44") == "40-64"
    assert smoking.broad_group("60-64") == "40-64"
    assert smoking.broad_group("65-69") == "65+"
    assert smoking.broad_group("80+") == "65+"


def toy() -> pd.DataFrame:
    """Twelve rows in one adult group, plus a child, with smoking levels 1, 2, 3 and unknown."""
    rows = []
    for level, cost, count in (("3", 100.0, 4), ("1", 60.0, 2), ("2", 80.0, 2)):
        for _ in range(count):
            rows.append(("40-44", level, cost, 1.0))
    rows += [("40-44", "3", 0.0, 1.0), ("40-44", "1", 0.0, 1.0)]
    rows += [("05-14", "3", 500.0, 1.0), ("40-44", "unknown", 9999.0, 1.0)]
    bands = ["05-14", "40-44"]
    frame = pd.DataFrame(rows, columns=["age", smoking.SMOKING, "capped_cost", "exposure"])
    frame["age"] = pd.Categorical(frame["age"], categories=bands)
    frame[smoking.SMOKING] = pd.Categorical(
        frame[smoking.SMOKING], categories=["3", "1", "2", "unknown"]
    )
    return frame


def test_adults_excludes_children_and_labels_the_group():
    out = smoking.adults(toy())
    assert (out["age"] == "40-44").all() and set(out["broad_group"]) == {"40-64"}
    assert len(out) == len(toy()) - 1


def test_crude_relativities_by_hand_and_the_unknown_level_is_left_out():
    table = smoking.crude_by_group(toy()).set_index("smoking")
    # non-smokers: 5 person-years and cost 400, so 80 per exposure year, rate 0.8, severity 100
    assert table.loc["every day", "person_years"] == 3
    assert table.loc["every day", "crude_cost_relativity"] == pytest.approx((120 / 3) / 80)
    assert table.loc["every day", "crude_frequency_relativity"] == pytest.approx((2 / 3) / 0.8)
    assert table.loc["every day", "crude_severity_relativity"] == pytest.approx(60 / 100)
    assert table.loc["some days", "crude_cost_relativity"] == pytest.approx((160 / 2) / 80)
    any_smoker = table.loc["any smoker"]
    assert any_smoker["person_years"] == 5
    assert any_smoker["crude_cost_relativity"] == pytest.approx((280 / 5) / 80)
    assert set(table["age_group"]) == {"40-64"}


def test_rebase_drops_unused_levels_and_puts_the_busiest_level_first():
    out = smoking.adults(toy())
    out = smoking.rebase(out.drop(columns="broad_group"), ["age", smoking.SMOKING])
    assert list(out["age"].cat.categories) == ["40-44"]
    assert out[smoking.SMOKING].cat.categories[0] == "3"
    assert "unknown" in out[smoking.SMOKING].cat.categories  # kept, but never the reference


def _built() -> bool:
    import duckdb

    from health_pricing.data.load import DUCKDB_PATH

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
def test_real_refit_without_flags_has_the_same_smokers_and_the_age_groups_are_fitted():
    prepared = glm.prepare_frames(mf.load_frames())
    table = smoking.with_and_without_flags(prepared)
    assert set(table["model"]) == {"with condition flags", "without condition flags"}
    assert set(table["smoking"]) == {"every day", "some days"}
    with_flags = table[table["model"] == "with condition flags"].set_index("smoking")
    final = factors.fit_option(prepared.train, factors.FINAL_RATING, factors.controls_for("final"))
    assert with_flags.loc["every day", "frequency_relativity"] == pytest.approx(
        float(np.exp(final.frequency.params["OFTSMK53=1"]))
    )
    adjusted = smoking.adjusted_by_group(prepared)
    assert set(adjusted["age_group"]) == {"18-39", "40-64", "65+"}
    crude = smoking.crude_by_group(prepared.train)
    assert set(crude["age_group"]) == {"18-39", "40-64", "65+"}
