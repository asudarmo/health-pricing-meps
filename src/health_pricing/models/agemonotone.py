"""A monotone adult age rule for the GLM tariff (M6, issue #57).

UK private medical premiums rise with age, so the adult age relativities (18 and over) of the tariff
must be non-decreasing. The rule is an exposure-weighted isotonic adjustment (pool adjacent
violators) of the adult band relativities. Bands that break the order are pooled to their
exposure-weighted mean. Children's bands (0 to 17) are left as fitted. The base is then rebalanced
on 2022 train, so predicted cost on train equals what the unadjusted tariff predicted there. The
frozen tariff of M3 is not changed. This module builds the adjusted tariff beside it.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from health_pricing.models import glm, metrics, relativities
from health_pricing.models.outofsample import FrozenModel

FACTOR = "age"
ADJUSTED = "GLM tariff, monotone adult age"
ORIGINAL = "GLM tariff"


def pava(values, weights) -> np.ndarray:
    """The weighted non-decreasing fit of `values` (pool adjacent violators)."""
    blocks: list[list[float]] = []  # each block holds [weighted mean, weight, count]
    for value, weight in zip(np.asarray(values, float), np.asarray(weights, float), strict=True):
        blocks.append([value, weight, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            last, previous = blocks.pop(), blocks.pop()
            weight_sum = previous[1] + last[1]
            mean = (previous[0] * previous[1] + last[0] * last[1]) / weight_sum
            blocks.append([mean, weight_sum, previous[2] + last[2]])
    return np.concatenate([np.full(int(count), mean) for mean, _, count in blocks])


def lower_age(level: str) -> int:
    """The lowest age of a band label such as `25-29` or `80+`."""
    return int(re.match(r"\d+", level).group())


def adult_bands(levels) -> list[str]:
    """The adult bands (18 and over) in order of age."""
    return sorted((str(level) for level in levels if lower_age(str(level)) >= 18), key=lower_age)


@dataclass
class AdjustedTariff:
    """The tariff with its adult age coefficients replaced and the base rebalanced."""

    base: object  # the SurrogateTariff of the frozen model
    coefficients: pd.Series  # all coefficients, adjusted
    balance: float  # multiplier on the base rate that restores the train total

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        matrix = glm.design_matrix(frame, self.base.factors, rating=True)
        matrix = matrix.reindex(columns=self.base.columns, fill_value=0.0)
        linear = matrix.to_numpy() @ self.coefficients.to_numpy()
        return self.balance * np.exp(linear + np.log(frame["exposure"].to_numpy()))


def monotone_adult_rule(
    relativity: pd.Series, exposure: pd.Series, cost: pd.Series
) -> tuple[pd.Series, float]:
    """The rule on band relativities, indexed by age band label (all bands, children included).

    The adult bands are pooled by `pava` with `exposure` as weights, and children are left as
    given. `cost` is the predicted cost of each band under the relativities as given. Returns the
    adjusted relativities and the base-rate multiplier that keeps the total predicted cost equal
    to what it was before the rule.
    """
    bands = adult_bands(relativity.index)
    adjusted = relativity.astype(float).copy()
    adjusted[bands] = pava(relativity[bands].to_numpy(), exposure[bands].to_numpy())
    new_cost = (cost * adjusted / relativity).sum()
    return adjusted, float(cost.sum() / new_cost)


def adjust(frozen: FrozenModel) -> AdjustedTariff:
    """Apply the isotonic rule to the adult age relativities and rebalance on train."""
    return adjust_tariff(frozen.final_tariff.tariff, frozen.prepared.train)


def adjust_tariff(tariff, train: pd.DataFrame) -> AdjustedTariff:
    """Apply the rule to a surrogate tariff, with exposure and cost taken from `train`."""
    params = tariff.result.params.copy()
    bands = [str(level) for level in train[FACTOR].cat.categories]
    terms = {band: f"{FACTOR}={band}" for band in bands if f"{FACTOR}={band}" in params.index}
    relativity = pd.Series(
        {b: float(np.exp(params[terms[b]])) if b in terms else 1.0 for b in bands}
    )
    exposure = train.groupby(FACTOR, observed=True)["exposure"].sum()
    predicted = pd.Series(tariff.predict(train), index=train.index)
    cost = predicted.groupby(train[FACTOR].astype(str).to_numpy()).sum()
    adjusted, balance = monotone_adult_rule(
        relativity, exposure.rename(index=str)[bands], cost[bands]
    )
    for band, term in terms.items():
        params[term] = np.log(adjusted[band])
    return AdjustedTariff(tariff, params, balance)


def band_table(frozen: FrozenModel, adjusted: AdjustedTariff) -> pd.DataFrame:
    """Age relativities before and after, rebased to the adult band with the most exposure.

    Both columns are divided by the same number, the relativity of that band before the rule, so a
    change is a change in the relativity. The rebasing changes how the table reads and not the
    model. The rebalancing moves the base rate and not the relativities (see `adjust`).
    """
    train = frozen.prepared.train
    params = frozen.final_tariff.tariff.result.params
    bands = [str(level) for level in train[FACTOR].cat.categories]
    exposure = train.groupby(FACTOR, observed=True)["exposure"].sum()
    before = {
        b: 1.0 if i == 0 else float(np.exp(params[f"{FACTOR}={b}"])) for i, b in enumerate(bands)
    }
    after = {
        b: 1.0 if i == 0 else float(np.exp(adjusted.coefficients[f"{FACTOR}={b}"]))
        for i, b in enumerate(bands)
    }
    reference = relativities.age_reference_for_presentation(frozen.raw)
    rows = []
    for band in sorted(bands, key=lower_age):
        rows.append(
            {
                "age_band": band,
                "adult": lower_age(band) >= 18,
                "exposure": float(exposure[band]),
                "relativity_before": before[band] / before[reference],
                "relativity_after": after[band] / before[reference],
            }
        )
    out = pd.DataFrame(rows)
    out["change_pct"] = 100 * (out["relativity_after"] / out["relativity_before"] - 1)
    out["changed"] = out["change_pct"].abs() > 1e-9
    return out


def score_table(frozen: FrozenModel, adjusted: AdjustedTariff) -> pd.DataFrame:
    """Deviance at three powers, Gini and A/E of the tariff before and after, on train and test."""
    rows = []
    for split in ("train", "test"):
        frame = getattr(frozen.prepared, split)
        for name, predicted in (
            (ORIGINAL, frozen.tariff(frame)),
            (ADJUSTED, adjusted.predict(frame)),
        ):
            rows.append(glm.candidate_scores(name, 0, {split: (frame, predicted)}))
    return pd.concat(rows, ignore_index=True).drop(columns=["parameters", "dropped_reason"])


def ae_by_band(frozen: FrozenModel, adjusted: AdjustedTariff, split: str = "test") -> pd.DataFrame:
    """A/E by age band before and after, on a split."""
    frame = getattr(frozen.prepared, split)
    first = metrics.ae_by_factor(frame, frozen.tariff(frame), [FACTOR])
    second = metrics.ae_by_factor(frame, adjusted.predict(frame), [FACTOR])
    out = first[["level", "person_years", "claimants", "actual", "expected", "a_e"]].merge(
        second[["level", "expected", "a_e"]], on="level", suffixes=("_before", "_after")
    )
    out.insert(0, "split", split)
    out["_order"] = out["level"].map(lower_age)
    return out.sort_values("_order").drop(columns="_order").reset_index(drop=True)


SEED_FOLDS = 5


@dataclass
class CrossValidation:
    """Out-of-fold results of the tariff before and after the rule."""

    scores: pd.DataFrame  # deviance, Gini and A/E on the pooled out-of-fold rows
    ae_by_band: pd.DataFrame
    folds: pd.DataFrame  # base-rate multiplier and the bands the rule changed, by fold


def cross_validate(frozen: FrozenModel, n_folds: int = SEED_FOLDS) -> CrossValidation:
    """Refit the tariff on each fold's training rows, apply the rule, and score the held-out fold.

    Folds hold whole households (`DUID`). The grouping of levels is kept as decided on the full
    2022 train split. Each fold refits the technical model, extracts the tariff, applies the rule
    and rebalances on its own training rows.
    """
    from sklearn.model_selection import GroupKFold

    from health_pricing.models import agecurve

    train, raw = frozen.prepared.train, frozen.raw.train
    held, before, after, folds = [], [], [], []
    for number, (fit_rows, test_rows) in enumerate(
        GroupKFold(n_splits=n_folds).split(train, groups=train["DUID"]), start=1
    ):
        prepared = dataclasses.replace(
            frozen.prepared, train=train.iloc[fit_rows], test=train.iloc[test_rows]
        )
        fold_raw = dataclasses.replace(
            frozen.raw, train=raw.iloc[fit_rows], test=raw.iloc[test_rows]
        )
        tariff = agecurve.final_tariff(prepared, fold_raw).tariff
        adjusted = adjust_tariff(tariff, prepared.train)
        frame = prepared.test
        held.append(frame)
        before.append(tariff.predict(frame))
        after.append(adjusted.predict(frame))
        pooled = tariff.result.params.filter(like=f"{FACTOR}=")
        moved = pooled.round(12).ne(adjusted.coefficients[pooled.index].round(12))
        folds.append(
            {
                "fold": number,
                "base_rate_multiplier": adjusted.balance,
                "bands_changed": int(moved.sum()),
            }
        )
    frame = pd.concat(held)
    predicted = {ORIGINAL: np.concatenate(before), ADJUSTED: np.concatenate(after)}
    scores = pd.concat(
        [
            glm.candidate_scores(name, 0, {"out_of_fold": (frame, values)})
            for name, values in predicted.items()
        ],
        ignore_index=True,
    ).drop(columns=["parameters", "dropped_reason"])
    first = metrics.ae_by_factor(frame, predicted[ORIGINAL], [FACTOR])
    second = metrics.ae_by_factor(frame, predicted[ADJUSTED], [FACTOR])
    ae = first[["level", "person_years", "claimants", "actual", "expected", "a_e"]].merge(
        second[["level", "expected", "a_e"]], on="level", suffixes=("_before", "_after")
    )
    ae["_order"] = ae["level"].map(lower_age)
    ae = ae.sort_values("_order").drop(columns="_order").reset_index(drop=True)
    return CrossValidation(scores, ae, pd.DataFrame(folds))


OUTPUT_DIR = relativities.OUTPUT_DIR.parent / "m6_draft"


def save_all(frozen: FrozenModel | None = None) -> dict[str, pd.DataFrame]:
    """Build the adjusted tariff and save the before and after tables under `outputs/m6_draft/`."""
    from health_pricing.models import outofsample

    frozen = frozen or outofsample.freeze()
    adjusted = adjust(frozen)
    tables = {
        "age_monotone_bands.csv": band_table(frozen, adjusted),
        "age_monotone_scores.csv": score_table(frozen, adjusted),
        "age_monotone_ae_by_band_test.csv": ae_by_band(frozen, adjusted, "test"),
        "age_monotone_ae_by_band_train.csv": ae_by_band(frozen, adjusted, "train"),
        "age_monotone_balance.csv": pd.DataFrame({"base_rate_multiplier": [adjusted.balance]}),
    }
    cv_result = cross_validate(frozen)
    tables["age_monotone_cv_scores.csv"] = cv_result.scores
    tables["age_monotone_cv_ae_by_band.csv"] = cv_result.ae_by_band
    tables["age_monotone_cv_folds.csv"] = cv_result.folds
    for name, table in tables.items():
        outofsample.save_table(table, name, OUTPUT_DIR)
    return tables


if __name__ == "__main__":
    save_all()
