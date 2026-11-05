"""Tests for the v1-lite final tariff (M6, issue #37)."""

import duckdb
import numpy as np
import pytest

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import agemonotone, finaltariff, outofsample


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
    return frozen, agemonotone.adjust(frozen)


def test_base_rate_times_relativities_reproduces_the_tariff(setup):
    frozen, adjusted = setup
    table = finaltariff.relativity_table(frozen, adjusted)
    base = finaltariff.base_rate_table(frozen, adjusted).set_index("component")["value"]
    lookup = table.set_index(["factor", "level"])["relativity"]
    frame = frozen.prepared.test.head(300)
    product = np.full(len(frame), base["base rate at 2022 level"])
    for factor in frozen.final_tariff.tariff.factors:
        product = product * np.array([lookup[(factor, str(v))] for v in frame[factor]])
    assert product * frame["exposure"].to_numpy() == pytest.approx(adjusted.predict(frame))
    assert base["base rate"] == pytest.approx(
        base["base rate at 2022 level"] * finaltariff.RATING_LEVEL
    )


def test_adult_age_relativities_never_fall_and_bounds_bracket_the_relativity(setup):
    frozen, adjusted = setup
    table = finaltariff.relativity_table(frozen, adjusted)
    age = table[table["factor"] == "age"].set_index("level")
    adults = age.loc[agemonotone.adult_bands(age.index), "relativity"]
    assert (adults.diff().dropna() >= -1e-12).all()
    bounded = table.dropna(subset=["lower_95"])
    assert (bounded["lower_95"] <= bounded["relativity"] + 1e-9).all()
    assert (bounded["relativity"] <= bounded["upper_95"] + 1e-9).all()
    assert age.loc["65-69", "age_rule_applied"] and not age.loc["35-39", "age_rule_applied"]


def test_approximation_error_covers_the_four_segment_types_and_rule_only_moves_older_ages(setup):
    frozen, adjusted = setup
    errors = finaltariff.approximation_error(frozen, adjusted, "train")
    assert set(errors["segment_type"]) == {
        "age band",
        "factor level",
        "predicted cost decile",
        "number of conditions",
    }
    age = errors[errors["segment_type"] == "age band"].set_index("segment")
    assert (age.loc["18-24":"55-59", "ratio_before_rule"] - 1).abs().max() < 1e-6
    assert errors.loc[errors["segment_type"] == "age band", "tariff_final"].sum() == pytest.approx(
        errors.loc[errors["segment_type"] == "age band", "tariff_before_rule"].sum(), rel=1e-9
    )
    summary = finaltariff.error_summary(errors)
    assert (summary["max_abs_departure_final"] >= summary["median_abs_departure_final"]).all()
