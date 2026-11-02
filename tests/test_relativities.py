"""Tests for the relativity tables (issue #34)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import factors, glm, large_claims, surrogate
from health_pricing.models import frame as mf
from health_pricing.models import relativities as rel


def toy(n=3000, seed=31) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    a = rng.choice(["r", "x", "y"], n, p=[0.5, 0.3, 0.2])
    b = rng.choice(["r", "z"], n)
    exposure = rng.uniform(0.3, 1.0, n)
    rate = (
        0.3 * np.where(a == "x", 1.6, 1.0) * np.where(a == "y", 0.7, 1.0) * np.where(b == "z", 2, 1)
    )
    claimed = rng.random(n) < 1 - np.exp(-rate * exposure)
    cost = np.where(claimed, rng.gamma(2.0, 900.0 * np.where(b == "z", 1.4, 1.0)), 0.0)
    return pd.DataFrame(
        {
            "a": pd.Categorical(a, categories=["r", "x", "y"]),
            "b": pd.Categorical(b, categories=["r", "z"]),
            "exposure": exposure,
            "capped_cost": cost,
        }
    )


@pytest.fixture
def fitted():
    train = toy()
    model = glm.fit_two_part(train, "cloglog", ["a", "b"])
    frequency = rel.component_table(model, train, "frequency")
    severity = rel.component_table(model, train, "severity")
    return train, model, frequency, severity


def test_reference_levels_have_a_relativity_of_one_and_no_interval(fitted):
    _, _, frequency, severity = fitted
    for table in (frequency, severity):
        reference = table[table["is_reference"]]
        assert set(reference["factor"]) == {"a", "b"}
        assert (reference["relativity"] == 1.0).all()
        assert (reference["lower_95"] == 1.0).all() and (reference["upper_95"] == 1.0).all()
        others = table[~table["is_reference"]]
        assert (others["lower_95"] < others["relativity"]).all()
        assert (others["relativity"] < others["upper_95"]).all()


def test_relativities_are_the_exponentials_of_the_coefficients_with_train_counts(fitted):
    train, model, frequency, _ = fitted
    line = frequency[(frequency["factor"] == "a") & (frequency["level"] == "x")].iloc[0]
    assert line["relativity"] == pytest.approx(np.exp(model.frequency.params["a=x"]))
    assert line["exposure"] == pytest.approx(train.loc[train["a"] == "x", "exposure"].sum())
    claimed = (train["capped_cost"] > 0) & (train["a"] == "x")
    assert line["claimants"] == claimed.sum()
    assert frequency.groupby("factor")["exposure"].sum().tolist() == pytest.approx(
        [train["exposure"].sum()] * 2
    )


def test_the_combined_table_is_the_product_with_bounds_that_add_in_quadrature(fitted):
    _, model, frequency, severity = fitted
    combined = rel.combined_table(frequency, severity).set_index(["factor", "level"])
    f = frequency.set_index(["factor", "level"])
    s = severity.set_index(["factor", "level"])
    key = ("b", "z")
    assert combined.loc[key, "relativity"] == pytest.approx(
        f.loc[key, "relativity"] * s.loc[key, "relativity"]
    )
    error = np.hypot(f.loc[key, "log_error"], s.loc[key, "log_error"])
    assert combined.loc[key, "upper_95"] == pytest.approx(
        combined.loc[key, "relativity"] * np.exp(rel.Z95 * error)
    )
    assert combined.loc[("a", "r"), "relativity"] == 1.0
    assert combined.loc[key, "lower_95"] < combined.loc[key, "relativity"]


def test_a_prediction_recomputed_from_the_base_values_matches_the_model_exactly(fitted):
    train, model, frequency, severity = fitted
    rates = rel.base_rates(model)
    for index in range(0, 300, 11):
        row = train.iloc[[index]]
        profile = {"a": str(row["a"].iloc[0]), "b": str(row["b"].iloc[0])}
        mine = rel.predict_from_relativities(
            profile, float(row["exposure"].iloc[0]), frequency, severity, rates, rebalance=1.2
        )
        assert mine == pytest.approx(model.predict(row)[0] * 1.2, rel=1e-12)


def test_exposure_and_the_load_enter_the_recomputed_prediction(fitted):
    _, model, frequency, severity = fitted
    rates = rel.base_rates(model)
    profile = {"a": "x", "b": "z"}
    whole = rel.predict_from_relativities(profile, 1.0, frequency, severity, rates, load=0.0)
    half = rel.predict_from_relativities(profile, 0.5, frequency, severity, rates, load=0.0)
    hazard = (
        rates["base_value"].iloc[0]
        * frequency.set_index(["factor", "level"])
        .loc[[("a", "x"), ("b", "z")], "relativity"]
        .prod()
    )
    assert 1 - np.exp(-hazard) == pytest.approx(
        whole
        / (
            rates["base_value"].iloc[1]
            * np.prod(
                severity.set_index(["factor", "level"]).loc[[("a", "x"), ("b", "z")], "relativity"]
            )
        )
    )
    assert half < whole
    loaded = rel.predict_from_relativities(profile, 1.0, frequency, severity, rates)
    assert loaded == pytest.approx(whole * (1 + large_claims.PROVISIONAL_LOAD))


def test_a_level_outside_the_tables_is_priced_at_the_reference(fitted):
    _, model, frequency, severity = fitted
    rates = rel.base_rates(model)
    base = rel.predict_from_relativities({"a": "r", "b": "r"}, 1.0, frequency, severity, rates)
    unknown = rel.predict_from_relativities(
        {"a": "unknown", "b": "r"}, 1.0, frequency, severity, rates
    )
    assert base == unknown


def test_presentation_rebases_age_only_and_keeps_the_technical_table(fitted):
    train, _, frequency, severity = fitted
    train = train.assign(age=train["a"])
    combined = rel.combined_table(frequency, severity).assign(
        factor=lambda d: d["factor"].replace({"a": "age"})
    )
    out = rel.add_presentation(combined, "x")
    age = out[out["factor"] == "age"].set_index("level")
    assert age.loc["x", "presentation_relativity"] == pytest.approx(1.0)
    assert age.loc["y", "presentation_relativity"] == pytest.approx(
        age.loc["y", "relativity"] / age.loc["x", "relativity"]
    )
    other = out[out["factor"] == "b"]
    assert other["presentation_relativity"].tolist() == other["relativity"].tolist()
    assert list(out.columns) == rel.TABLE_COLUMNS


def test_the_tariff_table_is_the_surrogate_relativities_with_no_interval():
    train = toy()
    response = np.exp(np.where(train["a"] == "x", 0.4, 0.0)) * train["exposure"].to_numpy() * 500
    tariff = surrogate.fit_surrogate_tariff(train, response, ["a", "b"])
    table = rel.tariff_table(tariff, train, ["a", "b"])
    line = table[(table["factor"] == "a") & (table["level"] == "x")].iloc[0]
    assert line["relativity"] == pytest.approx(np.exp(0.4))
    assert table[table["is_reference"]]["relativity"].eq(1.0).all()
    assert table["lower_95"].isna().all()


def test_save_table_writes_aggregates(tmp_path, fitted):
    _, _, frequency, severity = fitted
    table = rel.combined_table(frequency, severity)
    path = rel.save_table(table, "x.csv", tmp_path / "out")
    assert pd.read_csv(path).shape[0] == len(table)


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
def test_real_final_relativities_reproduce_the_final_prediction_to_1e_8():
    raw = mf.load_frames()
    prepared = glm.prepare_frames(raw)
    model = rel.fit_final(prepared)
    frequency = rel.component_table(model, prepared.train, "frequency")
    severity = rel.component_table(model, prepared.train, "severity")
    rates = rel.base_rates(model)
    result = factors.scored_option(
        prepared, "final", factors.FINAL_RATING, factors.controls_for("final")
    )
    for split, frame in (("train", prepared.train), ("test", prepared.test)):
        for index in range(0, len(frame), 211):
            row = frame.iloc[[index]]
            profile = {f: str(row[f].iloc[0]) for f in factors.FINAL_RATING}
            mine = rel.predict_from_relativities(
                profile, float(row["exposure"].iloc[0]), frequency, severity, rates,
                result.rebalance_factor,
            )  # fmt: skip
            assert mine == pytest.approx(result.candidate.prediction(split)[index], rel=1e-8)
    assert set(frequency["role"]) == {"rating", "analysis_only"}
    assert rel.age_reference_for_presentation(raw) == "65-69"
    reference = frequency[frequency["is_reference"]]
    assert (reference["relativity"] == 1.0).all()
