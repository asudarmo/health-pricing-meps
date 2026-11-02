"""A smooth adult age curve for the final structure, compared with the five-year bands (issue #41).

The child bands (0 to 4, 5 to 14, 15 to 17) are kept. Adult age is fitted as a natural cubic spline
with 3 or 4 degrees of freedom, so it is linear beyond the outer knots. A spline is not nested in
a set of bands, so the two are compared in three ways. AIC is computed at a common Gamma
dispersion, likelihood-ratio tests are run against a model that holds both, and the test
deviance is scored with the rebalancing used for every option. If the spline is preferred, the
tariff's band relativities are read off the smooth curve by fitting the surrogate model (tariff)
to the spline model's predictions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from health_pricing.models import factors, glm, surrogate
from health_pricing.models.frame import Frames

CHILD_BANDS = ["05-14", "00-04", "15-17"]  # the first is the reference
ADULT = "adult"
ADULT_AGE = 18
TOP_AGE = 85
KNOT_QUANTILES = {3: (0.05, 0.35, 0.65, 0.95), 4: (0.05, 0.275, 0.5, 0.725, 0.95)}
REFERENCE_AGE = 67  # the middle of the 65 to 69 band, where the smooth curve is set to 1


def natural_spline_basis(x, knots) -> np.ndarray:
    """A restricted cubic spline basis, with K knots and K - 1 columns, one per degree of freedom.

    The first column is x itself. The others are cubic terms that are forced to be linear beyond the
    outer knots. Each is scaled by the squared span of the knots to keep the numbers small.
    """
    x = np.asarray(x, dtype=float)
    t = np.asarray(knots, dtype=float)
    count = len(t)
    span = t[-1] - t[-2]

    def cube(value):
        return np.maximum(value, 0.0) ** 3

    columns = [x]
    for j in range(count - 2):
        term = (
            cube(x - t[j])
            - cube(x - t[-2]) * (t[-1] - t[j]) / span
            + cube(x - t[-1]) * (t[-2] - t[j]) / span
        )
        columns.append(term / (t[-1] - t[0]) ** 2)
    return np.column_stack(columns)


def knots_for(adult_ages, df: int) -> np.ndarray:
    """Knots at quantiles of the adult ages of the train split."""
    return np.quantile(np.asarray(adult_ages, dtype=float), KNOT_QUANTILES[df])


def spline_columns(df: int) -> list[str]:
    return [f"age_spline_{i}" for i in range(1, df + 1)]


def with_spline(frame: pd.DataFrame, ages, knots, df: int) -> pd.DataFrame:
    """Add `age_group3` (child bands and `adult`) and the spline terms, which are 0 for children.

    `ages` are the ages in years of the rows of `frame`, in the same order.
    """
    ages = np.asarray(ages, dtype=float)
    adult = ages >= ADULT_AGE
    out = frame.copy()
    label = np.where(adult, ADULT, out["age"].astype(object))
    out["age_group3"] = pd.Categorical(label, categories=[*CHILD_BANDS, ADULT])
    basis = natural_spline_basis(np.minimum(ages, TOP_AGE), knots)
    for name, column in zip(spline_columns(df), basis.T, strict=True):
        out[name] = np.where(adult, column, 0.0)
    return out


@dataclass
class AgeModel:
    name: str
    model: glm.TwoPartModel
    controls: list[str]
    knots: np.ndarray | None
    df: int | None

    def raw(self, frame: pd.DataFrame) -> np.ndarray:
        return factors.predict_option(self.model, frame, self.controls)


def _other_factors() -> list[str]:
    return [f for f in factors.FINAL_RATING if f != "age"]


def fit_age_models(prepared: Frames, raw: Frames, df: int) -> dict[str, AgeModel]:
    """The banded final model, the spline model and a model that holds both, fitted on train.

    `raw` are the frames before grouping, which hold age in years in the same row order.
    """
    controls = factors.controls_for("final")
    train_ages = raw.train["age"].astype(int).to_numpy()
    knots = knots_for(train_ages[train_ages >= ADULT_AGE], df)
    train = with_spline(prepared.train, train_ages, knots, df)
    numeric = tuple(spline_columns(df))
    other = _other_factors()
    bands = glm.fit_two_part(train, "cloglog", [*factors.FINAL_RATING, *controls], name="bands")
    spline = glm.fit_two_part(
        train, "cloglog", ["age_group3", *other, *controls], name="spline", numeric=numeric
    )
    both = glm.fit_two_part(
        train, "cloglog", [*factors.FINAL_RATING, *controls], name="both", numeric=numeric
    )
    return {
        "bands": AgeModel("bands", bands, controls, None, None),
        "spline": AgeModel("spline", spline, controls, knots, df),
        "both": AgeModel("both", both, controls, knots, df),
    }


def model_frames(prepared: Frames, raw: Frames, models: dict[str, AgeModel]) -> dict[str, Frames]:
    """The train and test frames with the spline terms, for each model that needs them."""
    out = {}
    for name, entry in models.items():
        if entry.knots is None:
            out[name] = prepared
            continue
        train_ages = raw.train["age"].astype(int).to_numpy()
        test_ages = raw.test["age"].astype(int).to_numpy()
        out[name] = Frames(
            with_spline(prepared.train, train_ages, entry.knots, entry.df),
            with_spline(prepared.test, test_ages, entry.knots, entry.df),
            prepared.reference_levels,
        )
    return out


def comparison_table(models: dict[str, AgeModel], frames: dict[str, Frames]) -> pd.DataFrame:
    """Parameters, AIC at a common dispersion, and the rebalanced test scores of each model.

    The common Gamma dispersion is that of the model that holds both curves. The AIC of the
    severity part is its deviance over that dispersion plus twice its parameters, and the
    frequency part uses the usual AIC. Test scores are rebalanced on train, as for every option.
    """
    phi = float(models["both"].model.severity.scale)
    rows = []
    for name, entry in models.items():
        model = entry.model
        train, test = frames[name].train, frames[name].test
        balance = factors.rebalance_factor(train, entry.raw(train))
        scores = glm.candidate_scores(
            name, model.parameters, {"test": (test, entry.raw(test) * balance)}
        ).iloc[0]
        severity_aic = model.severity.deviance / phi + 2 * len(model.severity.params)
        rows.append(
            {
                "model": name,
                "parameters": model.parameters,
                "frequency_deviance": float(model.frequency.deviance),
                "severity_deviance": float(model.severity.deviance),
                "aic": float(model.frequency.aic + severity_aic),
                "test_deviance": float(scores["tweedie_deviance"]),
                "test_gini": float(scores["gini"]),
            }
        )
    out = pd.DataFrame(rows)
    out["aic_change_from_bands"] = out["aic"] - out.loc[out["model"] == "bands", "aic"].iloc[0]
    return out


def encompassing_tests(models: dict[str, AgeModel]) -> pd.DataFrame:
    """Likelihood-ratio tests of each curve against the model that holds both.

    The statistic is the fall in deviance from the smaller model to the model that holds both,
    divided by the Gamma dispersion of the latter for the severity part, summed over the two parts.
    A small p-value means the curve that was left out adds something.
    """
    both = models["both"].model
    rows = []
    for name, left_out in (("bands", "spline"), ("spline", "bands")):
        small = models[name].model
        statistic, df = 0.0, 0.0
        for part in ("frequency", "severity"):
            big, little = getattr(both, part), getattr(small, part)
            statistic += (little.deviance - big.deviance) / big.scale
            df += big.df_model - little.df_model
        rows.append(
            {
                "model_tested": name,
                "curve_added": left_out,
                "lr_statistic": float(statistic),
                "df": float(df),
                "p_value": float(stats.chi2.sf(statistic, df)),
            }
        )
    return pd.DataFrame(rows)


def spline_curve(entry: AgeModel, ages=range(ADULT_AGE, TOP_AGE + 1)) -> pd.DataFrame:
    """The relativity of each adult age against age 67, from the spline model.

    The frequency and severity relativities come from the spline coefficients, and the combined
    relativity is their product. Other factors cancel in the ratio.
    """
    ages = np.asarray(list(ages), dtype=float)
    basis = natural_spline_basis(ages, entry.knots)
    reference = natural_spline_basis([REFERENCE_AGE], entry.knots)[0]
    names = spline_columns(entry.df)
    out = pd.DataFrame({"age": ages.astype(int)})
    for part in ("frequency", "severity"):
        beta = getattr(entry.model, part).params[names].to_numpy()
        out[f"{part}_relativity"] = np.exp((basis - reference) @ beta)
    out["combined_relativity"] = out["frequency_relativity"] * out["severity_relativity"]
    return out


def smooth_tariff(
    prepared: Frames, entry: AgeModel, frames: Frames
) -> tuple[surrogate.SurrogateTariff, np.ndarray]:
    """The surrogate model (tariff) with five-year age bands, fitted to the spline model's cost.

    The response is smooth in age, so the band relativities read off the tariff follow the smooth
    curve. The predictions are rebalanced on train. Returns the tariff and its train predictions.
    """
    train_prediction = entry.raw(frames.train)
    balance = factors.rebalance_factor(frames.train, train_prediction)
    tariff = surrogate.fit_surrogate_tariff(
        prepared.train, train_prediction * balance, factors.FINAL_RATING
    )
    return tariff, train_prediction * balance
