"""Tests for the rating engine (M6, issue #60)."""

import dataclasses

import numpy as np
import pytest

from health_pricing.models import agemonotone, outofsample
from health_pricing.rating import engine

VERSION = "m6_draft"
CONDITIONS = ["HIBPDX", "CHDDX", "OHRTDX", "CHOLDX", "CANCERDX", "ARTHDX", "ASTHDX"]


@pytest.fixture(scope="module")
def tariff():
    if not (engine.OUTPUTS / VERSION / engine.RELATIVITIES).exists():
        pytest.skip("run python -m health_pricing.models.finaltariff")
    return dataclasses.replace(engine.load_tariff(VERSION), scaling=None)


def _profile(**changes):
    return {"age": 40, "region": "3", **dict.fromkeys(CONDITIONS, "0"), **changes}


def test_breakdown_multiplies_to_the_premium(tariff):
    result = engine.rate(_profile(age=67, CANCERDX=1, region="1"), tariff=tariff)
    assert result["breakdown"]["factor"].prod() == pytest.approx(result["premium"])
    assert result["breakdown"]["step"].iloc[0] == "base rate at 2022 level"
    assert {"forecast trend", "rebase"} <= set(result["breakdown"]["step"])


def test_engine_reproduces_the_final_tariff_for_every_observed_rating_cell(tariff):
    frozen = outofsample.freeze()
    adjusted = agemonotone.adjust(frozen)
    frame = frozen.prepared.train
    keys = ["age", "region", *CONDITIONS]
    cells = frame.drop_duplicates(keys).copy()
    cells["exposure"] = 1.0
    expected = adjusted.predict(cells) * tariff.trend * tariff.rebase
    lower = {label: low for low, _, label in tariff.age_bands}
    got = [
        engine.rate(
            {k: (lower[str(row[k])] if k == "age" else str(row[k])) for k in keys}, tariff=tariff
        )["premium"]
        for row in cells.to_dict("records")
    ]
    assert len(cells) > 500
    assert np.allclose(got, expected, rtol=1e-9)


def test_premium_never_falls_with_adult_age(tariff):
    premiums = [engine.rate(_profile(age=a), tariff=tariff)["premium"] for a in range(18, 101)]
    assert (np.diff(premiums) >= -1e-9).all()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sex": "F"}, "not permitted"),
        ({"income": 1}, "not permitted"),
        ({"age": -1}, "between"),
        ({"age": 121}, "between"),
        ({"age": 40.5}, "whole number"),
        ({"region": "9"}, "Allowed"),
        ({"CHDDX": "maybe"}, "Allowed"),
        ({"colour": "blue"}, "Unknown"),
    ],
)
def test_invalid_profiles_fail_with_a_clear_message(tariff, changes, message):
    with pytest.raises(engine.ProfileError, match=message):
        engine.rate(_profile(**changes), tariff=tariff)


def test_missing_field_fails_and_analysis_only_controls_are_priced_at_reference(tariff):
    profile = _profile()
    del profile["region"]
    with pytest.raises(engine.ProfileError, match="Missing"):
        engine.rate(profile, tariff=tariff)
    plain = engine.rate(_profile(), tariff=tariff)
    smoker = engine.rate(_profile(OFTSMK53="1", rthlth="5"), tariff=tariff)
    assert smoker["premium"] == plain["premium"]
    assert smoker["priced_at_reference"] == ["OFTSMK53", "rthlth"]


def test_unknown_model_version_fails():
    with pytest.raises(FileNotFoundError):
        engine.load_tariff("no_such_version")


def test_scaling_is_given_only_when_the_version_has_one(tariff):
    assert "premium_illustrative_gbp" not in engine.rate(_profile(), tariff=tariff)
    scaled = dataclasses.replace(tariff, scaling={"gbp_per_usd_premium": 0.5})
    result = engine.rate(_profile(), tariff=scaled)
    assert result["premium_illustrative_gbp"] == pytest.approx(0.5 * result["premium"])
    assert result["illustrative"] is True
    assert result["illustrative_label"].startswith("risk premium (expected claims cost)")
    assert "excluding expenses and margin" in result["breakdown"]["step"].iloc[-1]
    assert result["breakdown"]["factor"].prod() == pytest.approx(result["premium_illustrative_gbp"])


def test_the_decided_scaling_is_recorded_with_its_source_and_label():
    version = engine.load_tariff(VERSION)
    assert version.scaling["gbp_per_usd_premium"] == 0.244
    assert "ABI" in version.scaling["source"] and "6 November 2024" in version.scaling["source"]
    result = engine.rate(_profile(), tariff=version)
    assert result["premium_illustrative_gbp"] == pytest.approx(0.244 * result["premium"])
    assert result["illustrative_label"] == engine.GBP_LABEL
