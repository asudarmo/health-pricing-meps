"""A monotone adult age rule for the GLM tariff (M6, issue #57).

UK private medical premiums rise with age, so the adult age relativities (18 and over) of the tariff
must be non-decreasing. The rule is an exposure-weighted isotonic adjustment (pool adjacent
violators) of the adult band relativities. Bands that break the order are pooled to their
exposure-weighted mean. Children's bands (0 to 17) are left as fitted. The base is then rebalanced
on 2022 train, so predicted cost on train equals what the unadjusted tariff predicted there. The
frozen tariff of M3 is not changed. This module builds the adjusted tariff beside it.
"""

from __future__ import annotations

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


def adjust(frozen: FrozenModel) -> AdjustedTariff:
    """Apply the isotonic rule to the adult age relativities and rebalance on train."""
    tariff = frozen.final_tariff.tariff
    train = frozen.prepared.train
    params = tariff.result.params.copy()
    bands = adult_bands(train[FACTOR].cat.categories)
    exposure = train.groupby(FACTOR, observed=True)["exposure"].sum()
    terms = [f"{FACTOR}={band}" for band in bands]
    relativity = np.exp(params[terms].to_numpy())
    pooled = pava(relativity, exposure.loc[bands].to_numpy())
    params[terms] = np.log(pooled)
    unadjusted = AdjustedTariff(tariff, params, 1.0)
    balance = float(tariff.predict(train).sum() / unadjusted.predict(train).sum())
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
    for name, table in tables.items():
        outofsample.save_table(table, name, OUTPUT_DIR)
    return tables


if __name__ == "__main__":
    save_all()
