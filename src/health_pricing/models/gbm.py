"""A LightGBM challenger to the GLM, with its surrogate tariff (M4-lite).

One gradient-boosting model with a Tweedie objective (power 1.5) is fitted to the capped annual
cost of each person-year, with log exposure as the init score (an offset). Its inputs are the 9
rating factors of the final structure, with adult age as a number that the model may only increase
with, and `inscov` as a control that is priced at the private level when scoring, as in the GLM.
Predictions carry the provisional large-claim load and are rebalanced on 2022 train in the same way
as the GLM. The GLM is not changed. The model is tuned by grouped cross-validation on 2022 train,
with every fold holding whole households.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from health_pricing.models import (
    agecurve,
    factors,
    glm,
    large_claims,
    metrics,
    outofsample,
    surrogate,
    trend,
)
from health_pricing.models.frame import Frames
from health_pricing.models.outofsample import FrozenModel

SEED = 20231103
OUTPUT_DIR = outofsample.OUTPUT_DIR.parent / "m4_draft"
POWER = 1.5
CONTROL = "inscov"
ADULT_AGE = "age_adult"
CHILD_AGE = "age_group3"
RATING_CODES = [f for f in factors.FINAL_RATING if f != "age"]
FEATURES = [CHILD_AGE, ADULT_AGE, *RATING_CODES, CONTROL]
CATEGORICAL = [CHILD_AGE, "region", CONTROL]
N_FOLDS = 5
MAX_ROUNDS = 2000
EARLY_STOP = 50
GRID = {
    "learning_rate": [0.03, 0.06],
    "num_leaves": [4, 8, 16],
    "min_data_in_leaf": [50, 150],
}
BASELINE = "Baseline (2022 train mean)"
NAMES = {
    "gbm": "GBM",
    "gbm_tariff": "GBM tariff",
    "glm_technical": "GLM technical model",
    "glm_tariff": "GLM tariff",
}


def feature_matrix(frame: pd.DataFrame, price: bool = False) -> pd.DataFrame:
    """The model inputs of a frame with grouped factors and the age spline terms.

    Adult age (at most 85) enters as a number, with 18 for children, whose age is in the child
    bands. The other factors enter as the codes of their levels, reference level first. When
    `price` is set the control is at its reference level.
    """
    out = pd.DataFrame(index=frame.index)
    adult = frame[CHILD_AGE].astype(str) == agecurve.ADULT
    out[CHILD_AGE] = frame[CHILD_AGE].cat.codes
    out[ADULT_AGE] = np.where(adult, frame["age_spline_1"], float(agecurve.ADULT_AGE))
    for name in [*RATING_CODES, CONTROL]:
        out[name] = frame[name].cat.codes
    if price:
        out[CONTROL] = 0
    return out[FEATURES]


def parameters(
    learning_rate: float, num_leaves: int, min_data_in_leaf: int, seed: int = SEED
) -> dict:
    """The LightGBM parameters, with a monotone increasing constraint on adult age."""
    return {
        "objective": "tweedie",
        "tweedie_variance_power": POWER,
        "metric": "tweedie",
        "learning_rate": learning_rate,
        "num_leaves": num_leaves,
        "min_data_in_leaf": min_data_in_leaf,
        "monotone_constraints": [1 if name == ADULT_AGE else 0 for name in FEATURES],
        "seed": seed,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 1,
        "verbosity": -1,
    }


def dataset(frame: pd.DataFrame, free: bool = False) -> lgb.Dataset:
    """A LightGBM dataset of capped cost with the offset of log exposure as init score."""
    return lgb.Dataset(
        feature_matrix(frame),
        label=frame["capped_cost"].to_numpy(),
        init_score=np.log(frame["exposure"].to_numpy()),
        categorical_feature=CATEGORICAL,
        free_raw_data=free,
    )


def raw_cost(model: lgb.Booster, frame: pd.DataFrame, rounds: int | None = None) -> np.ndarray:
    """Expected capped cost of each person-year, with the control priced at its reference level."""
    score = model.predict(feature_matrix(frame, price=True), raw_score=True, num_iteration=rounds)
    return np.exp(score + np.log(frame["exposure"].to_numpy()))


def combinations(grid: dict = GRID) -> list[dict]:
    """Every combination of the grid, in a fixed order."""
    out = [{}]
    for name, values in grid.items():
        out = [{**base, name: value} for base in out for value in values]
    return out


def fold_indices(
    train: pd.DataFrame, n_folds: int = N_FOLDS
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Fit and validation rows of each fold. A household is never split across the two."""
    return list(GroupKFold(n_splits=n_folds).split(train, groups=train["DUID"]))


def tune(
    train: pd.DataFrame, grid: dict = GRID, n_folds: int = N_FOLDS, seed: int = SEED
) -> pd.DataFrame:
    """Grouped cross-validation of every combination, with early stopping on the trees.

    Folds hold whole households (`DUID`). Each combination is scored by the Tweedie deviance
    (power 1.5) of its out-of-fold predictions of capped cost, and the number of trees is the mean
    best iteration of the folds.
    """
    folds = fold_indices(train, n_folds)
    rows = []
    for combination in combinations(grid):
        predicted = np.zeros(len(train))
        trees = []
        for fit_index, valid_index in folds:
            fit, valid = train.iloc[fit_index], train.iloc[valid_index]
            booster = lgb.train(
                parameters(**combination, seed=seed),
                dataset(fit),
                num_boost_round=MAX_ROUNDS,
                valid_sets=[dataset(valid)],
                callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)],
            )
            trees.append(booster.best_iteration)
            predicted[valid_index] = raw_cost(booster, valid, booster.best_iteration)
        rows.append(
            {
                **combination,
                "trees": int(round(np.mean(trees))),
                "min_trees": int(min(trees)),
                "max_trees": int(max(trees)),
                "cv_deviance_p1_5": metrics.tweedie_deviance(train["capped_cost"], predicted),
            }
        )
    table = pd.DataFrame(rows)
    table["chosen"] = table["cv_deviance_p1_5"] == table["cv_deviance_p1_5"].min()
    return table


@dataclass
class Fitted:
    """The final GBM, its tree count and the balance factor of 2022 train."""

    model: lgb.Booster
    trees: int
    balance: float
    chosen: dict

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        """Predicted annual cost with the load and the balance, for a frame with spline terms."""
        load = 1 + large_claims.PROVISIONAL_LOAD
        return raw_cost(self.model, frame, self.trees) * load * self.balance


def fit(train: pd.DataFrame, table: pd.DataFrame, seed: int = SEED) -> Fitted:
    """Fit the chosen combination on all of 2022 train and balance it on train."""
    chosen = table[table["chosen"]].iloc[0]
    combination = {name: chosen[name] for name in GRID}
    combination["num_leaves"] = int(combination["num_leaves"])
    combination["min_data_in_leaf"] = int(combination["min_data_in_leaf"])
    trees = int(chosen["trees"])
    booster = lgb.train(parameters(**combination, seed=seed), dataset(train), trees)
    load = 1 + large_claims.PROVISIONAL_LOAD
    balance = factors.rebalance_factor(train, raw_cost(booster, train) * load)
    return Fitted(booster, trees, balance, combination)


def surrogate_tariff(
    fitted: Fitted, spline_train: pd.DataFrame, prepared: Frames
) -> tuple[surrogate.SurrogateTariff, np.ndarray]:
    """The multiplicative surrogate model (tariff) of the GBM, fitted to its train predictions.

    The factors are the rating factors with age in five-year bands, as for the GLM tariff, and the
    predictions are the balanced ones, so the tariff keeps the total of train cost.
    """
    predicted = fitted.predict(spline_train)
    tariff = surrogate.fit_surrogate_tariff(prepared.train, predicted, factors.FINAL_RATING)
    return tariff, predicted


def predictions(
    frozen: FrozenModel, fitted: Fitted, gbm_tariff: surrogate.SurrogateTariff, split: str
) -> dict[str, np.ndarray]:
    """The four models' predicted annual cost on the 2022 `train` or `test` split."""
    spline = getattr(frozen.final_tariff.frames["spline"], split)
    grouped = getattr(frozen.prepared, split)
    return {
        NAMES["gbm"]: fitted.predict(spline),
        NAMES["gbm_tariff"]: gbm_tariff.predict(grouped),
        NAMES["glm_technical"]: frozen.technical(spline),
        NAMES["glm_tariff"]: frozen.tariff(grouped),
    }


def scores(
    frozen: FrozenModel, predicted: dict[str, np.ndarray], split: str = "test"
) -> pd.DataFrame:
    """Deviance at three powers, the reduction against the baseline, Gini and A/E on a split."""
    frame = getattr(frozen.prepared, split)
    baseline = metrics.baseline_predictions(frozen.prepared.train, frame)
    table = pd.concat(
        [
            glm.candidate_scores(name, 0, {split: (frame, values)})
            for name, values in {BASELINE: baseline, **predicted}.items()
        ],
        ignore_index=True,
    )
    base = table.loc[table["candidate"] == BASELINE]
    for column in ("tweedie_deviance", "tweedie_deviance_p1_3", "tweedie_deviance_p1_7"):
        table[f"reduction_pct_{column.replace('tweedie_deviance', 'dev')}"] = 100 * (
            1 - table[column] / base[column].iloc[0]
        )
    return table.drop(columns=["parameters", "dropped_reason"])


def deviance_gaps(
    frame: pd.DataFrame,
    predicted: dict[str, np.ndarray],
    pairs: list[tuple[str, str]],
    n_boot: int = trend.N_BOOT,
    seed: int = SEED,
) -> pd.DataFrame:
    """Deviance of the first model of each pair less that of the second, with household intervals.

    A positive gap means the second model fits better. The gap is also given in points of the
    baseline deviance. Households are resampled with replacement, with a fixed seed.
    """
    households = pd.factorize(frame["DUID"])[0]
    units = {
        name: metrics.tweedie_unit_deviance(frame["cost"].to_numpy(), values)
        for name, values in predicted.items()
    }
    names = sorted({name for pair in pairs for name in pair})
    count = households.max() + 1
    sums = np.zeros((count, len(names)))
    for k, name in enumerate(names):
        sums[:, k] = np.bincount(households, weights=units[name], minlength=count)
    resampled = trend.resampled_sums(sums, n_boot, seed)
    rows = []
    for first, second in pairs:
        i, j = names.index(first), names.index(second)
        gap = sums[:, i].sum() - sums[:, j].sum()
        draws = resampled[:, i] - resampled[:, j]
        low, high = np.quantile(draws, [0.025, 0.975])
        rows.append(
            {
                "first": first,
                "second": second,
                "deviance_gap": float(gap),
                "lower_95": float(low),
                "upper_95": float(high),
                "interval_excludes_0": bool(low > 0 or high < 0),
            }
        )
    return pd.DataFrame(rows)


def survival(table: pd.DataFrame, column: str = "gini") -> dict[str, float]:
    """The share of the GBM's advantage over the GLM tariff that its surrogate tariff keeps.

    For Gini the advantage is a rise, and for a deviance it is a fall. The share is not defined
    (it is NaN) when the GBM has no advantage over the GLM tariff.
    """
    values = table.set_index("candidate")[column]
    sign = -1.0 if "deviance" in column else 1.0
    glm_tariff = values[NAMES["glm_tariff"]]
    advantage = sign * (values[NAMES["gbm"]] - glm_tariff)
    kept = sign * (values[NAMES["gbm_tariff"]] - glm_tariff)
    return {
        "gbm_advantage": float(advantage),
        "surrogate_advantage": float(kept),
        "share_kept": float(kept / advantage) if advantage > 0 else float("nan"),
    }


def shap_values(fitted: Fitted, matrix: pd.DataFrame) -> np.ndarray:
    """SHAP values on the log scale of expected cost, one column per feature."""
    import shap

    return shap.TreeExplainer(fitted.model).shap_values(matrix, check_additivity=False)


def shap_age_curve(values: np.ndarray, matrix: pd.DataFrame) -> pd.DataFrame:
    """The mean SHAP value of adult age by year of age, relative to age 67."""
    k = FEATURES.index(ADULT_AGE)
    adult = matrix[CHILD_AGE] == matrix[CHILD_AGE].max()
    frame = pd.DataFrame(
        {"age": matrix.loc[adult, ADULT_AGE].astype(int), "shap": values[adult.to_numpy(), k]}
    )
    curve = frame.groupby("age")["shap"].mean().rename("gbm_log_effect").reset_index()
    curve["gbm_log_effect"] -= float(
        curve.loc[curve["age"] == agecurve.REFERENCE_AGE, "gbm_log_effect"].iloc[0]
    )
    return curve


def top_interactions(fitted: Fitted, matrix: pd.DataFrame, top: int = 5) -> pd.DataFrame:
    """The feature pairs with the largest mean absolute SHAP interaction value."""
    import shap

    values = shap.TreeExplainer(fitted.model).shap_interaction_values(matrix)
    mean = np.abs(values).mean(axis=0)
    rows = [
        {"feature_a": FEATURES[a], "feature_b": FEATURES[b], "mean_abs_interaction": mean[a, b]}
        for a in range(len(FEATURES))
        for b in range(a + 1, len(FEATURES))
    ]
    return pd.DataFrame(rows).nlargest(top, "mean_abs_interaction").reset_index(drop=True)


def double_lift(
    frame: pd.DataFrame, predicted: dict[str, np.ndarray], first: str, second: str, n: int = 10
) -> pd.DataFrame:
    """Double lift of `first` against `second`: groups by the ratio of the two predictions."""
    table = metrics.double_lift_table(
        frame["cost"], predicted[first], predicted[second], frame["exposure"], n
    )
    return table.rename(
        columns={
            "predicted_a": f"predicted {first}",
            "predicted_b": f"predicted {second}",
            "a_e_a": f"A/E {first}",
            "a_e_b": f"A/E {second}",
        }
    )


def forecast_predictions(
    frozen: FrozenModel,
    oot,
    fitted: Fitted,
    gbm_tariff: surrogate.SurrogateTariff,
    factor: float,
) -> dict[str, np.ndarray]:
    """The four models on 2023 with the forecast trend as a factor on expected cost."""
    from health_pricing.models import monitoring
    from health_pricing.models.outofsample import TARIFF, TECHNICAL

    glm_predictions = monitoring.forecast(frozen, oot, factor)
    return {
        NAMES["gbm"]: fitted.predict(oot.spline_frame) * factor,
        NAMES["gbm_tariff"]: gbm_tariff.predict(oot.frame) * factor,
        NAMES["glm_technical"]: glm_predictions[TECHNICAL],
        NAMES["glm_tariff"]: glm_predictions[TARIFF],
    }


def save_table(table: pd.DataFrame, name: str, directory=OUTPUT_DIR):
    """Save an aggregate table under `outputs/m4_draft/`."""
    return outofsample.save_table(table, name, directory)
