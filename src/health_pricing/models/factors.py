"""Permitted rating factors and factor selection for the chosen structure (issue #39).

The structure is candidate (a): a cloglog claimant frequency and a Gamma severity. A factor that
is analysis-only is fitted as a control, so it adjusts the other relativities, and is priced at
its reference level when predicting. That is the treatment agreed for `inscov`. The options below
set which factors are rating factors. Each rating factor is then tested by dropping it from the
structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from health_pricing.models import comparison, glm, metrics
from health_pricing.models.frame import FACTORS, Frames

CONDITION_FLAGS = [
    "HIBPDX", "CHDDX", "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX", "CANCERDX", "ARTHDX",
    "ASTHDX", "DIABDX_M18",
]  # fmt: skip
ANALYSIS_ONLY = ["rthlth", "mnhlth", "PHYEXE53", "inscov"]
# The factors that stay rating factors under each option, and the rest are analysis-only controls.
OPTIONS = {
    "all_factors": FACTORS,
    "option_1": [f for f in FACTORS if f not in ANALYSIS_ONLY],
    "option_2": [f for f in FACTORS if f not in ANALYSIS_ONLY and f not in CONDITION_FLAGS],
}
# The factor rule approved at gate 7, part 2: keep a rating factor only if the likelihood-ratio test
# gives p < 0.05 and AIC improves. Applied to option 1 it drops these four, leaving 10 factors.
SELECTION_P_VALUE = 0.05
DROPPED_BY_RULE = ["ANGIDX", "MIDX", "STRKDX", "DIABDX_M18"]
RATING_AFTER_RULE = [f for f in OPTIONS["option_1"] if f not in DROPPED_BY_RULE]
# Smoking passes the rule, but the user decided at the smoking gate that it is analysis-only. It
# is fitted as a control and priced at the non-smoker level, so the tariff has no smoker discount.
SMOKING = "OFTSMK53"
FINAL_RATING = [f for f in RATING_AFTER_RULE if f != SMOKING]
OPTIONS["rule_selected"] = RATING_AFTER_RULE
OPTIONS["final"] = FINAL_RATING
OUTPUT_DIR = glm.SCORES_DIR


def controls_for(option: str) -> list[str]:
    """The analysis-only factors of an option, in the order of the factor list.

    A factor dropped by the selection rule is left out of the fit and is not a control. The
    final structure also holds smoking as a control.
    """
    if option == "rule_selected":
        return [f for f in FACTORS if f in ANALYSIS_ONLY]
    if option == "final":
        return [f for f in FACTORS if f in ANALYSIS_ONLY or f == SMOKING]
    return [f for f in FACTORS if f not in OPTIONS[option]]


def at_reference(frame: pd.DataFrame, controls: list[str]) -> pd.DataFrame:
    """A copy of the frame with each control set to its reference level (the first category)."""
    out = frame.copy()
    for factor in controls:
        categories = list(out[factor].cat.categories)
        out[factor] = pd.Categorical([categories[0]] * len(out), categories=categories)
    return out


def fit_option(train: pd.DataFrame, rating: list[str], controls: list[str]) -> glm.TwoPartModel:
    """Candidate (a) with the given rating factors, and the controls fitted but not priced."""
    return glm.fit_two_part(train, "cloglog", factors=[*rating, *controls], name="a")


def predict_option(model: glm.TwoPartModel, frame: pd.DataFrame, controls: list[str]) -> np.ndarray:
    """Expected annual cost with each control priced at its reference level."""
    return model.predict(at_reference(frame, controls))


def rebalance_factor(train: pd.DataFrame, predicted) -> float:
    """The factor that makes predicted cost on train equal actual cost on train.

    Pricing a control at its reference level leaves the base rate too low for the book as a whole,
    because the reference level is not the average. Rebalancing the base rate is the usual remedy
    when a factor is left out of the tariff. It uses train only.
    """
    return float(train["cost"].sum() / np.sum(predicted))


@dataclass
class OptionResult:
    """A set of rating factors fitted and predicted, rebalanced on train."""

    candidate: comparison.Candidate
    rebalance_factor: float
    rating_factors: int


def scored_option(
    prepared: Frames, name: str, rating: list[str], controls: list[str]
) -> OptionResult:
    """Fit candidate (a) with these rating factors and controls, and rebalance its predictions.

    The predictions are scaled so that train predicted cost equals train actual cost.
    """
    model = fit_option(prepared.train, rating, controls)
    train = predict_option(model, prepared.train, controls)
    test = predict_option(model, prepared.test, controls)
    balance = rebalance_factor(prepared.train, train)
    candidate = comparison.Candidate(
        name, model.parameters, train * balance, test * balance, train * balance, test * balance
    )
    return OptionResult(candidate, balance, len(rating))


def option_results(prepared: Frames) -> dict[str, OptionResult]:
    """Every option in `OPTIONS` fitted on train and predicted on both splits."""
    return {
        name: scored_option(prepared, name, rating, controls_for(name))
        for name, rating in OPTIONS.items()
    }


def select_by_aic(tests: pd.DataFrame) -> list[str]:
    """The tested factors whose removal would worsen AIC, so that keeping them is supported."""
    return list(tests.loc[tests["keep_by_aic"], "factor"])


def select_by_rule(tests: pd.DataFrame, p_value: float = SELECTION_P_VALUE) -> list[str]:
    """The factors to keep: the likelihood-ratio test gives p below the limit and AIC improves."""
    keep = tests["keep_by_aic"] & (tests["p_value"] < p_value)
    return list(tests.loc[keep, "factor"])


def add_back_sensitivity(
    prepared: Frames,
    factor: str,
    rating: list[str] = FINAL_RATING,
    controls: list[str] | None = None,
) -> pd.DataFrame:
    """What a dropped factor would do if it were added back to the final factor set.

    The table gives the relativity of each level in the fuller structure (frequency and
    severity) and the test deviance (p = 1.5) with and without the factor. Both are rebalanced.
    A negative change is an improvement.
    """
    controls = controls_for("final") if controls is None else controls
    base = scored_option(prepared, "final", rating, controls)
    plus = scored_option(prepared, f"final_plus_{factor}", [*rating, factor], controls)
    model = fit_option(prepared.train, [*rating, factor], controls)
    effect = adjusted_effect(model, prepared.train, factor)
    rows = []
    for _, line in effect.iterrows():
        scores = {}
        for name, result in (("without", base), ("with", plus)):
            frame_scores = glm.candidate_scores(
                name, 0, {"test": (prepared.test, result.candidate.test)}
            )
            scores[name] = frame_scores.loc[0, "tweedie_deviance"]
        rows.append(
            {
                "factor": factor,
                "level": line["level"],
                "frequency_relativity": line["frequency_relativity"],
                "severity_relativity": line["severity_relativity"],
                "test_deviance_without": scores["without"],
                "test_deviance_with": scores["with"],
                "change_in_test_deviance": scores["with"] - scores["without"],
            }
        )
    return pd.DataFrame(rows)


def option_scores(prepared: Frames, results: dict[str, OptionResult]) -> pd.DataFrame:
    """The yardstick scores of each option on both splits, with the factor count and rebalancing."""
    frames = {"train": prepared.train, "test": prepared.test}
    rows = []
    for name, result in results.items():
        for split, frame in frames.items():
            candidate = result.candidate
            scores = glm.candidate_scores(
                name, candidate.parameters, {split: (frame, candidate.prediction(split))}
            )
            scores.insert(2, "rating_factors", result.rating_factors)
            scores.insert(3, "rebalance_factor", result.rebalance_factor)
            rows.append(scores.drop(columns="dropped_reason"))
    baseline = metrics.baseline_scores(prepared.train, prepared.test)
    return metrics.add_deviance_reduction(pd.concat(rows, ignore_index=True), baseline)


def drop_one_tests(train: pd.DataFrame, rating: list[str], controls: list[str]) -> pd.DataFrame:
    """Test each rating factor by dropping it from the structure.

    The frequency and severity parts are fitted again without the factor. The likelihood-ratio
    statistic is the fall in deviance, divided by the dispersion of the fuller model (1 for the
    frequency part), summed over the two parts. It is compared with a chi-squared distribution on
    the extra degrees of freedom. The change in AIC is the AIC of the model without the factor
    minus the AIC of the full model, which is the statistic minus twice the degrees of freedom, so
    a positive value means the factor improves the fit. The severity part is evaluated at the
    dispersion of the full model, so the two models share one likelihood and AIC is comparable.
    """
    full = fit_option(train, rating, controls)
    rows = []
    for factor in rating:
        reduced = fit_option(train, [f for f in rating if f != factor], controls)
        statistic, df = 0.0, 0.0
        for part in ("frequency", "severity"):
            big, small = getattr(full, part), getattr(reduced, part)
            statistic += (small.deviance - big.deviance) / big.scale
            df += big.df_model - small.df_model
        change = statistic - 2 * df
        rows.append(
            {
                "factor": factor,
                "levels_dropped": int(df),
                "lr_statistic": float(statistic),
                "p_value": float(stats.chi2.sf(statistic, df)),
                "aic_change_if_dropped": float(change),
                "keep_by_aic": bool(change > 0),
            }
        )
    return pd.DataFrame(rows)


def save_table(table: pd.DataFrame, name: str, directory: Path = OUTPUT_DIR) -> Path:
    """Save an aggregate table in the draft outputs."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    table.to_csv(path, index=False)
    return path


def exercise_table(frame: pd.DataFrame, factor: str = "PHYEXE53", adult_age: int = 18):
    """Exercise level against claims for adults, before any adjustment.

    Children are not asked the question and are left out. `frame` is a prepared frame. Cost is the
    capped annual cost.
    """
    adults = frame[frame["age"].astype(object).map(lambda a: _lower_age(a) >= adult_age)]
    grouped = adults.groupby(factor, observed=True)
    table = grouped.agg(
        person_years=("exposure", "size"),
        exposure=("exposure", "sum"),
        claimants=("capped_cost", lambda c: int((c > 0).sum())),
        capped_cost=("capped_cost", "sum"),
        mean_age=("age", lambda a: float(np.mean([_lower_age(x) for x in a]))),
    )
    table["claimant_rate"] = table["claimants"] / table["person_years"]
    table["capped_cost_per_exposure_year"] = table["capped_cost"] / table["exposure"]
    return table.drop(columns="capped_cost").reset_index()


def _lower_age(band: str) -> int:
    return int(str(band).split("-")[0].rstrip("+"))


def adjusted_effect(model: glm.TwoPartModel, train: pd.DataFrame, factor: str) -> pd.DataFrame:
    """The relativities of a factor's levels in the fitted structure, with 95 percent intervals.

    The frequency and severity relativities are shown, and their product is the effect on expected
    cost per person-year at a given exposure when claims are rare. The interval is for each part.
    """
    table = glm.coefficient_table(model, train)
    rows = []
    for term in table.loc[table["term"].str.startswith(f"{factor}="), "term"].unique():
        row = {"level": term.split("=", 1)[1]}
        for part in ("frequency", "severity"):
            line = table[(table["part"] == part) & (table["term"] == term)].iloc[0]
            low = np.exp(line["coefficient"] - 1.96 * line["std_error"])
            high = np.exp(line["coefficient"] + 1.96 * line["std_error"])
            row[f"{part}_relativity"] = line["relativity"]
            row[f"{part}_lower_95"], row[f"{part}_upper_95"] = low, high
        row["claimants"] = int(line["claimants"])
        rows.append(row)
    return pd.DataFrame(rows)
