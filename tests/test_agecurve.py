"""Tests for the smooth adult age curve and the rebased age intervals (issue #41)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import agecurve as ac
from health_pricing.models import frame as mf
from health_pricing.models import glm, levels
from health_pricing.models import relativities as rel

KNOTS = np.array([21.0, 38.0, 53.0, 66.0, 81.0])


def test_the_basis_has_one_column_per_degree_of_freedom_and_starts_with_age():
    ages = np.arange(18, 86)
    for df, quantiles in ac.KNOT_QUANTILES.items():
        basis = ac.natural_spline_basis(ages, np.linspace(20, 80, len(quantiles)))
        assert basis.shape == (len(ages), df)
        assert basis[:, 0].tolist() == pytest.approx(ages.tolist())


def test_the_spline_is_linear_beyond_the_outer_knots():
    low = ac.natural_spline_basis(np.arange(5, 21), KNOTS)
    high = ac.natural_spline_basis(np.arange(82, 90), KNOTS)
    for block in (low, high):
        assert np.abs(np.diff(block, n=2, axis=0)).max() < 1e-12


def test_a_linear_function_is_in_the_span_and_a_smooth_bend_is_close():
    ages = np.arange(18, 86, dtype=float)
    basis = np.column_stack([np.ones(len(ages)), ac.natural_spline_basis(ages, KNOTS)])
    errors = []
    for target in (3.0 + 2.0 * ages, np.sin(ages / 15.0)):
        coefficients, *_ = np.linalg.lstsq(basis, target, rcond=None)
        errors.append(np.abs(basis @ coefficients - target).max())
    assert errors[0] < 1e-9 and errors[1] < 0.15


def test_knots_are_quantiles_of_the_adult_ages():
    ages = np.arange(18, 86)
    assert ac.knots_for(ages, 3) == pytest.approx(np.quantile(ages, [0.05, 0.35, 0.65, 0.95]))
    assert len(ac.knots_for(ages, 4)) == 5


def toy(n=2500, seed=5):
    rng = np.random.default_rng(seed)
    ages = rng.integers(0, 86, n)
    bands = ac_bands(ages)
    exposure = rng.uniform(0.3, 1.0, n)
    rate = 0.05 + 0.5 * np.clip((ages - 10) / 60, 0, 1) ** 1.5
    claimed = rng.random(n) < 1 - np.exp(-rate * exposure)
    cost = np.where(claimed, rng.gamma(2.0, 700.0 * (1 + ages / 50), n), 0.0)
    frame = pd.DataFrame(
        {
            "age": pd.Categorical(bands, categories=list(dict.fromkeys(sorted(set(bands))))),
            "exposure": exposure,
            "capped_cost": cost,
        }
    )
    return frame, ages


def ac_bands(ages):
    return [levels.age_label(int(a), levels.AGE_BANDS["five_year"]) for a in ages]


def test_with_spline_keeps_the_child_bands_and_zeroes_the_spline_for_children():
    frame, ages = toy()
    out = ac.with_spline(frame, ages, KNOTS, 4)
    child = ages < 18
    assert set(out.loc[child, "age_group3"].astype(str)) <= {"00-04", "05-14", "15-17"}
    assert (out.loc[~child, "age_group3"] == "adult").all()
    assert out.loc[child, ac.spline_columns(4)].to_numpy().max() == 0.0
    assert out.loc[~child, "age_spline_1"].to_numpy() == pytest.approx(
        np.minimum(ages[~child], 85).astype(float)
    )
    assert list(out["age_group3"].cat.categories) == [*ac.CHILD_BANDS, ac.ADULT]


def fit_spline(frame, ages, df=4):
    knots = ac.knots_for(ages[ages >= 18], df)
    data = ac.with_spline(frame, ages, knots, df)
    model = glm.fit_two_part(
        data, "cloglog", ["age_group3"], numeric=tuple(ac.spline_columns(df)), name="s"
    )
    return data, knots, model


def test_a_spline_model_fits_predicts_and_reports_the_spline_terms():
    frame, ages = toy()
    data, knots, model = fit_spline(frame, ages)
    for part in ("frequency", "severity"):
        assert all(name in getattr(model, part).params for name in ac.spline_columns(4))
    assert model.numeric == tuple(ac.spline_columns(4))
    assert (model.predict(data) > 0).all()
    table = glm.coefficient_table(model, data)
    assert set(ac.spline_columns(4)) <= set(table["term"])


def test_the_smooth_curve_is_one_at_the_reference_age_and_matches_the_coefficients():
    frame, ages = toy()
    _, knots, model = fit_spline(frame, ages)
    entry = ac.AgeModel("spline", model, [], knots, 4)
    curve = ac.spline_curve(entry, [ac.REFERENCE_AGE, 40, 80]).set_index("age")
    assert curve.loc[ac.REFERENCE_AGE, "combined_relativity"] == pytest.approx(1.0)
    basis = ac.natural_spline_basis([40, ac.REFERENCE_AGE], knots)
    beta = model.frequency.params[ac.spline_columns(4)].to_numpy()
    assert curve.loc[40, "frequency_relativity"] == pytest.approx(
        np.exp((basis[0] - basis[1]) @ beta)
    )
    assert curve.loc[80, "combined_relativity"] == pytest.approx(
        curve.loc[80, "frequency_relativity"] * curve.loc[80, "severity_relativity"]
    )


def banded_model():
    frame, _ = toy()
    return glm.fit_two_part(frame, "cloglog", ["age"], name="b"), frame


def test_rebased_intervals_are_a_contrast_of_the_coefficients():
    model, frame = banded_model()
    technical = frame["age"].cat.categories[0]
    table = rel.rebased_age_table(model, "65-69", technical)
    row = table[(table["level"] == "40-44") & (table["part"] == "frequency")].iloc[0]
    params, cov = model.frequency.params, model.frequency.cov_params()
    diff = params["age=40-44"] - params["age=65-69"]
    var = cov.loc["age=40-44", "age=40-44"] + cov.loc["age=65-69", "age=65-69"]
    var -= 2 * cov.loc["age=40-44", "age=65-69"]
    assert row["relativity"] == pytest.approx(np.exp(diff))
    assert row["lower_95"] == pytest.approx(np.exp(diff - 1.959963984540054 * np.sqrt(var)))
    # the reference has relativity 1 and no interval, and the old technical band is a ratio to it
    reference = table[(table["level"] == "65-69") & (table["part"] == "combined")].iloc[0]
    assert reference[["relativity", "lower_95", "upper_95"]].tolist() == pytest.approx([1, 1, 1])
    technical_row = table[(table["level"] == technical) & (table["part"] == "frequency")].iloc[0]
    assert technical_row["relativity"] == pytest.approx(np.exp(-params["age=65-69"]))
    assert technical_row["lower_95"] < technical_row["relativity"] < technical_row["upper_95"]


def test_the_combined_rebased_bounds_add_the_variances_of_the_parts():
    model, frame = banded_model()
    technical = frame["age"].cat.categories[0]
    table = rel.rebased_age_table(model, "65-69", technical).set_index(["level", "part"])
    frequency = table.loc[("40-44", "frequency")]
    severity = table.loc[("40-44", "severity")]
    combined = table.loc[("40-44", "combined")]
    assert combined["relativity"] == pytest.approx(frequency["relativity"] * severity["relativity"])
    half = lambda r: (np.log(r["upper_95"]) - np.log(r["lower_95"])) / 2  # noqa: E731
    assert half(combined) == pytest.approx(np.hypot(half(frequency), half(severity)))


def test_presentation_bounds_come_from_the_rebased_table_for_age_only():
    model, frame = banded_model()
    technical = frame["age"].cat.categories[0]
    frequency = rel.component_table(model, frame, "frequency")
    rebased = rel.rebased_age_table(model, "65-69", technical)
    out = rel.add_presentation(frequency, "65-69", rebased[rebased["part"] == "frequency"])
    age = out[out["factor"] == "age"].set_index("level")
    reference = age.loc["65-69"]
    assert reference["presentation_relativity"] == pytest.approx(1.0)
    assert reference["presentation_lower_95"] == pytest.approx(1.0)
    assert reference["presentation_upper_95"] == pytest.approx(1.0)
    technical_row = age.loc[technical]
    assert technical_row["lower_95"] == 1.0 and technical_row["presentation_lower_95"] < 1.0
    bare = rel.add_presentation(frequency, "65-69")
    assert bare.loc[bare["factor"] == "age", "presentation_lower_95"].isna().all()


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
def test_real_age_comparison_has_three_models_and_valid_tests():
    raw = mf.load_frames()
    prepared = glm.prepare_frames(raw)
    models = ac.fit_age_models(prepared, raw, 4)
    frames = ac.model_frames(prepared, raw, models)
    table = ac.comparison_table(models, frames).set_index("model")
    assert set(table.index) == {"bands", "spline", "both"}
    assert table.loc["bands", "aic_change_from_bands"] == 0.0
    assert table.loc["spline", "parameters"] < table.loc["bands", "parameters"]
    tests = ac.encompassing_tests(models).set_index("model_tested")
    assert tests["p_value"].between(0, 1).all()
    assert (
        tests.loc["bands", "df"] == 8 and tests.loc["spline", "df"] == 24
    )  # 4 per part, 12 per part
    phi = models["both"].model.severity.scale
    by_hand = models["spline"].model.frequency.aic + (
        models["spline"].model.severity.deviance / phi
        + 2 * len(models["spline"].model.severity.params)
    )
    assert table.loc["spline", "aic"] == pytest.approx(by_hand)
    # the model that holds both has the lowest deviance in each part
    for part in ("frequency", "severity"):
        both = getattr(models["both"].model, part).deviance
        assert both <= getattr(models["bands"].model, part).deviance + 1e-6
        assert both <= getattr(models["spline"].model, part).deviance + 1e-6
    tariff, train_prediction = ac.smooth_tariff(prepared, models["spline"], frames["spline"])
    assert train_prediction.sum() == pytest.approx(prepared.train["cost"].sum())
    assert tariff.predict(prepared.train).sum() == pytest.approx(train_prediction.sum(), rel=1e-6)
