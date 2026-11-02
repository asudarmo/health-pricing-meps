"""Tests for the surrogate model (tariff) (issue #32)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import comparison as cmp
from health_pricing.models import glm, surrogate

FACTORS = ["a", "b"]
RELATIVITY = {"x": 1.4, "y": 0.7, "z": 2.0}


def toy(n=900, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": pd.Categorical(rng.choice(["r", "x", "y"], n), categories=["r", "x", "y"]),
            "b": pd.Categorical(rng.choice(["r", "z"], n), categories=["r", "z"]),
            "exposure": rng.uniform(0.2, 1.0, n),
        }
    )


def multiplicative(frame, base=900.0) -> np.ndarray:
    a = frame["a"].astype(object).map(RELATIVITY).fillna(1.0)
    b = frame["b"].astype(object).map(RELATIVITY).fillna(1.0)
    return (base * a * b * frame["exposure"]).to_numpy()


def kinked(frame) -> np.ndarray:
    """Not multiplicative: the (x, z) cell is three times what the margins imply."""
    both = (frame["a"] == "x") & (frame["b"] == "z")
    return multiplicative(frame) * np.where(both, 3.0, 1.0)


def candidate(name, train, test=None) -> cmp.Candidate:
    test = train if test is None else test
    return cmp.Candidate(name, 3, train, test, train, test)


def test_a_multiplicative_response_is_recovered_exactly():
    frame = toy()
    tariff = surrogate.fit_surrogate_tariff(frame, multiplicative(frame), FACTORS)
    assert tariff.predict(frame) == pytest.approx(multiplicative(frame))
    relativities = tariff.relativities().set_index("term")["relativity"]
    assert relativities["a=x"] == pytest.approx(1.4)
    assert relativities["a=y"] == pytest.approx(0.7)
    assert relativities["b=z"] == pytest.approx(2.0)
    assert relativities["const"] == pytest.approx(900.0)  # the base rate per exposure year


def test_the_surrogate_is_multiplicative_even_when_the_response_is_not():
    frame = toy()
    tariff = surrogate.fit_surrogate_tariff(frame, kinked(frame), FACTORS)
    unit = tariff.predict(frame.assign(exposure=1.0))
    matrix = glm.design_matrix(frame, FACTORS, rating=True)
    assert cmp.multiplicative_departure(unit, matrix)["max_multiplicative_departure"] < 1e-9
    # and it does not reproduce the response, which is what the departure table measures
    assert np.abs(tariff.predict(frame) / kinked(frame) - 1).max() > 0.2


def test_the_surrogate_keeps_the_total_predicted_cost_and_scales_with_exposure():
    frame = toy()
    response = kinked(frame)
    tariff = surrogate.fit_surrogate_tariff(frame, response, FACTORS)
    assert tariff.predict(frame).sum() == pytest.approx(response.sum())
    row = frame.iloc[[0]]
    assert tariff.predict(row.assign(exposure=1.0)) == pytest.approx(
        2 * tariff.predict(row.assign(exposure=0.5))
    )


def test_the_response_is_the_prediction_and_not_the_claims():
    frame = toy()
    claims = np.random.default_rng(0).gamma(2.0, 400.0, len(frame))
    frame = frame.assign(cost=claims, claim_count=3)
    tariff = surrogate.fit_surrogate_tariff(frame, multiplicative(frame), FACTORS)
    # claims are random noise, so a fit to them could not reproduce the multiplicative prediction
    assert tariff.predict(frame) == pytest.approx(multiplicative(frame))


def test_departure_table_by_hand():
    reference = np.array([100.0, 200.0, 400.0, 800.0])
    surrogate_prediction = np.array([100.0, 220.0, 400.0, 600.0])
    table = surrogate.departure_from_reference(
        candidate("a", reference), candidate("s", surrogate_prediction)
    ).set_index("split")
    row = table.loc["train"]
    assert row["max_abs_departure"] == pytest.approx(0.25)
    assert row["median_abs_departure"] == pytest.approx(0.05)
    assert row["total_cost_ratio"] == pytest.approx(1320 / 1500)
    assert row["rms_log_departure"] == pytest.approx(
        np.sqrt(np.mean(np.log(surrogate_prediction / reference) ** 2))
    )
    assert list(table.index) == ["train", "test"]


def test_a_surrogate_candidate_can_be_scored_like_any_other():
    train, test = toy(), toy(seed=4)
    prepared = cmp.Frames(train, test, {})
    reference = candidate("a", kinked(train), kinked(test))
    tariff, scored = surrogate.surrogate_candidate(prepared, reference, factors=FACTORS)
    assert scored.name == "a_surrogate" and scored.parameters == tariff.parameters == 4
    assert len(scored.train) == len(train) and len(scored.test) == len(test)
    # the unit prediction is the same tariff at a full year of exposure
    assert scored.train_unit == pytest.approx(tariff.predict(train.assign(exposure=1.0)))
    frame = test.assign(cost=np.random.default_rng(1).gamma(2.0, 500.0, len(test)))
    scores = glm.candidate_scores("a_surrogate", scored.parameters, {"test": (frame, scored.test)})
    assert scores.loc[0, "tweedie_deviance"] > 0 and scores.loc[0, "parameters"] == 4
