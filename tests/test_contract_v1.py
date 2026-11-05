"""Contract test for `outputs/v1/`, the section 6 outputs (M6, issue #62)."""

import json

import numpy as np
import pandas as pd
import pytest

from health_pricing import publish
from health_pricing.rating import engine

DIRECTORY = engine.OUTPUTS / "v1"
FILES = [
    "model_version.json",
    "relativities.csv",
    "base_rate.csv",
    "scaling.json",
    "ae_table.csv",
    "psi_table.csv",
    "in_force_book.csv",
    "golden_cases.csv",
    "figures/scenario_example_dislocation.png",
]
PERSON_LEVEL = {"DUPERSID", "DUID", "PID", "person_id", "household_id", "weight", "PERWT22F"}


@pytest.fixture(scope="module", autouse=True)
def published():
    if not DIRECTORY.exists():
        pytest.skip("run python -m health_pricing.publish")


def _read(name):
    return pd.read_csv(DIRECTORY / name, dtype={"level": str, "region": str})


def test_every_contract_file_exists():
    for name in FILES:
        assert (DIRECTORY / name).exists(), name


def test_schemas_and_keys():
    assert list(_read("relativities.csv").columns) == publish.RELATIVITY_COLUMNS
    assert list(_read("ae_table.csv").columns) == publish.AE_COLUMNS
    assert list(_read("psi_table.csv").columns) == ["factor", "period", "psi"]
    assert not _read("relativities.csv").duplicated(["factor", "level"]).any()
    assert not _read("ae_table.csv").duplicated(["factor", "level", "segment", "period"]).any()
    assert not _read("psi_table.csv").duplicated(["factor", "period"]).any()
    meta = json.loads((DIRECTORY / "model_version.json").read_text())
    for key in ("id", "date", "data_years", "trend_assumptions", "validation_metrics"):
        assert key in meta
    assert {"tweedie_deviance", "gini"} <= set(meta["validation_metrics"]["test_split_2022"])
    assert meta["permitted_rating_factors"] == publish.PERMITTED


def test_no_person_level_field_and_no_forbidden_factor():
    for name in ("relativities.csv", "ae_table.csv", "psi_table.csv", "in_force_book.csv"):
        assert not PERSON_LEVEL & set(_read(name).columns), name
    factors = set(_read("relativities.csv")["factor"])
    assert not engine.NOT_PERMITTED & {f.lower() for f in factors}
    assert factors == set(publish.PERMITTED)


def test_totals_and_bounds():
    book = _read("in_force_book.csv")
    ae = _read("ae_table.csv")
    relativities = _read("relativities.csv")
    overall = ae[(ae["factor"] == "all") & (ae["period"] == publish.PERIOD_2022)]
    assert book["exposure"].sum() == pytest.approx(21541.083333, rel=1e-6)
    age = ae[(ae["factor"] == "age") & (ae["period"] == publish.PERIOD_2022)]
    assert age["exposure"].sum() == pytest.approx(overall["exposure"].iloc[0])
    bounded = relativities.dropna(subset=["lower_95"])
    assert (bounded["lower_95"] <= bounded["relativity"] + 1e-9).all()
    assert (bounded["relativity"] <= bounded["upper_95"] + 1e-9).all()
    adults = relativities[relativities["factor"] == "age"].set_index("level")["relativity"]
    adult = adults[[b for b in adults.index if int(b[:2]) >= 18]]
    assert (adult.diff().dropna() >= -1e-12).all()
    assert (relativities["exposure"] > 0).all()


def test_golden_cases_are_labelled_and_match_the_engine_and_the_tariff():
    golden = _read("golden_cases.csv")
    meta = json.loads((DIRECTORY / "model_version.json").read_text())
    assert (golden["status"] == publish.GOLDEN_LABEL).all()
    assert meta["golden_cases"]["status"] == publish.GOLDEN_LABEL
    tariff = engine.load_tariff("v1")
    keys = ["age", "region", *publish.finaltariff.CONDITIONS]
    for row in golden.to_dict("records"):
        profile = {k: (row[k] if k == "age" else str(row[k])) for k in keys}
        premium = engine.rate(profile, tariff=tariff)["premium"]
        assert row["expected_premium_usd"] == pytest.approx(premium)
        assert row["expected_premium_gbp"] == pytest.approx(0.244 * premium)
    assert len(golden) >= 30


def test_golden_cases_equal_the_final_tariff_predictions():
    from health_pricing.models import agemonotone, outofsample

    frozen = outofsample.freeze()
    adjusted = agemonotone.adjust(frozen)
    golden = _read("golden_cases.csv")
    tariff = engine.load_tariff("v1")
    train = frozen.prepared.train
    cells = train.drop_duplicates(["age", "region", *publish.finaltariff.CONDITIONS])
    lower = {label: low for low, _, label in tariff.age_bands}
    sample = cells.head(1).copy()
    for row in golden.head(3).to_dict("records"):
        label = next(lab for low, high, lab in tariff.age_bands if low <= row["age"] <= high)
        cell = sample.copy()
        cell["exposure"] = 1.0
        for key in ["region", *publish.finaltariff.CONDITIONS]:
            cell[key] = pd.Categorical([str(row[key])], categories=train[key].cat.categories)
        cell["age"] = pd.Categorical([label], categories=train["age"].cat.categories)
        expected = adjusted.predict(cell)[0] * tariff.trend * tariff.rebase
        assert row["expected_premium_usd"] == pytest.approx(expected)
    assert lower and np.isfinite(golden["expected_premium_usd"]).all()


def test_scaling_in_the_model_version_equals_scaling_json_and_the_dislocation_histogram_exists():
    meta = json.loads((DIRECTORY / "model_version.json").read_text())
    assert meta["uk_scaling"] == json.loads((DIRECTORY / "scaling.json").read_text())
    assert (DIRECTORY / "figures" / "scenario_example_dislocation.png").stat().st_size > 1000
