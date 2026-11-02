"""Relativity tables for the final structure (issue #34).

The final structure is candidate (a) on the 10 rating factors chosen at decision gate 7, part 2.
Its two parts are multiplicative on their own scales, so each part is a base value times one
relativity per factor level. The frequency part is a claim hazard, `1 - exp(-exposure * base *
product of relativities)`, and the severity part is `base * product of relativities`. The combined
pure premium is not exactly multiplicative, so its relativities come from the surrogate model
(tariff), which is fitted to the structure's predicted cost. Tables hold aggregates only. The
analysis-only factors are fitted as controls and priced at their reference level, so their
relativities are shown for information and are not used in the price.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from health_pricing.models import factors, glm, large_claims, levels, surrogate
from health_pricing.models.frame import Frames

OUTPUT_DIR = glm.SCORES_DIR
Z95 = 1.959963984540054
TABLE_COLUMNS = [
    "factor", "level", "role", "is_reference", "relativity", "presentation_relativity",
    "exposure", "claimants", "lower_95", "upper_95", "presentation_lower_95",
    "presentation_upper_95",
]  # fmt: skip


def role_of(factor: str) -> str:
    return "rating" if factor in factors.FINAL_RATING else "analysis_only"


def fit_final(prepared: Frames) -> glm.TwoPartModel:
    """Candidate (a) with the final rating factors, and the analysis-only controls fitted."""
    return factors.fit_option(prepared.train, factors.FINAL_RATING, factors.controls_for("final"))


def _level_counts(train: pd.DataFrame, factor: str) -> pd.DataFrame:
    """Exposure and claimants (a positive capped cost) of each level of a factor on train."""
    claimed = (train["capped_cost"] > 0).astype(int)
    table = pd.DataFrame(
        {"exposure": train["exposure"], "claimants": claimed, "level": train[factor]}
    )
    return table.groupby("level", observed=True).agg(
        exposure=("exposure", "sum"), claimants=("claimants", "sum")
    )


def component_table(model: glm.TwoPartModel, train: pd.DataFrame, part: str) -> pd.DataFrame:
    """Relativities of one part (`frequency` or `severity`) for every level of every factor.

    The reference level of a factor has a relativity of 1 and no interval. The exposure and the
    claimants are the train totals in the level. Bounds are 95 percent limits from the standard
    errors of the coefficients.
    """
    result = getattr(model, part)
    rows = []
    for factor in model.factors:
        counts = _level_counts(train, factor)
        categories = list(train[factor].cat.categories)
        for position, level in enumerate(categories):
            term = f"{factor}={level}"
            reference = position == 0
            if reference:
                coefficient, error = 0.0, 0.0
            elif term in result.params:
                coefficient, error = float(result.params[term]), float(result.bse[term])
            else:
                continue  # a level with no claimants in this part, or the `unknown` control
            rows.append(
                {
                    "factor": factor,
                    "level": level,
                    "role": role_of(factor),
                    "is_reference": reference,
                    "relativity": float(np.exp(coefficient)),
                    "exposure": float(counts["exposure"].get(level, 0.0)),
                    "claimants": int(counts["claimants"].get(level, 0)),
                    "lower_95": float(np.exp(coefficient - Z95 * error)),
                    "upper_95": float(np.exp(coefficient + Z95 * error)),
                    "log_error": error,
                }
            )
    return pd.DataFrame(rows)


def combined_table(frequency: pd.DataFrame, severity: pd.DataFrame) -> pd.DataFrame:
    """The combined pure premium relativity as the product of the two parts, with bounds.

    The bounds treat frequency and severity as independent, so the standard errors of the logs add
    in quadrature. They are approximate, and a level missing from one part takes that part as 1.
    """
    keys = ["factor", "level"]
    merged = frequency.merge(
        severity, on=keys, how="outer", suffixes=("_f", "_s"), validate="one_to_one"
    )
    merged["relativity_f"] = merged["relativity_f"].fillna(1.0)
    merged["relativity_s"] = merged["relativity_s"].fillna(1.0)
    error = np.sqrt(merged["log_error_f"].fillna(0.0) ** 2 + merged["log_error_s"].fillna(0.0) ** 2)
    relativity = merged["relativity_f"] * merged["relativity_s"]
    return pd.DataFrame(
        {
            "factor": merged["factor"],
            "level": merged["level"],
            "role": merged["role_f"].fillna(merged["role_s"]),
            "is_reference": merged["is_reference_f"].fillna(merged["is_reference_s"]),
            "relativity": relativity,
            "exposure": merged["exposure_f"].fillna(merged["exposure_s"]),
            "claimants": merged["claimants_f"].fillna(merged["claimants_s"]),
            "lower_95": relativity * np.exp(-Z95 * error),
            "upper_95": relativity * np.exp(Z95 * error),
            "log_error": error,
        }
    )


def tariff_table(
    tariff: surrogate.SurrogateTariff, train: pd.DataFrame, rating: list[str]
) -> pd.DataFrame:
    """Relativities of the surrogate model (tariff), which is exactly multiplicative.

    They are point values with no interval, because the model is fitted to predictions and not to
    claims. The reference level has a relativity of 1.
    """
    params = tariff.result.params
    rows = []
    for factor in rating:
        counts = _level_counts(train, factor)
        for position, level in enumerate(train[factor].cat.categories):
            term = f"{factor}={level}"
            if position > 0 and term not in params:
                continue
            rows.append(
                {
                    "factor": factor,
                    "level": level,
                    "role": "rating",
                    "is_reference": position == 0,
                    "relativity": 1.0 if position == 0 else float(np.exp(params[term])),
                    "exposure": float(counts["exposure"].get(level, 0.0)),
                    "claimants": int(counts["claimants"].get(level, 0)),
                    "lower_95": np.nan,
                    "upper_95": np.nan,
                    "log_error": np.nan,
                }
            )
    return pd.DataFrame(rows)


def _log_ratio(result, band: str, reference: str, technical: str) -> tuple[float, float]:
    """The log ratio of an age band to a reference band, and its variance, from a fitted part.

    The ratio is a contrast of the coefficients, so its variance is the contrast times the
    covariance matrix times the contrast. The technical reference band has no coefficient.
    """
    contrast = pd.Series(0.0, index=result.params.index)
    if band != technical:
        contrast[f"age={band}"] += 1.0
    if reference != technical:
        contrast[f"age={reference}"] -= 1.0
    covariance = result.cov_params()
    return float(contrast @ result.params), float(contrast @ covariance @ contrast)


def rebased_age_table(
    model: glm.TwoPartModel, reference_band: str, technical_reference: str
) -> pd.DataFrame:
    """Age relativities against `reference_band` with intervals from the covariance matrix.

    For each band the log of the ratio to the reference band is a contrast of the coefficients, with
    its variance from the covariance matrix. The combined ratio is the product of the frequency and
    severity ratios, and its bounds treat the two parts as independent, so they are approximate.
    The table has the columns `level`, `part`, `relativity`, `lower_95` and `upper_95`.
    """
    frequency = model.frequency.params.index
    bands = sorted(
        {technical_reference, *(t.split("=", 1)[1] for t in frequency if t.startswith("age="))}
    )
    rows = []
    for band in bands:
        logs = {
            part: _log_ratio(getattr(model, part), band, reference_band, technical_reference)
            for part in ("frequency", "severity")
        }
        logs["combined"] = (
            logs["frequency"][0] + logs["severity"][0],
            logs["frequency"][1] + logs["severity"][1],
        )
        for part, (diff, var) in logs.items():
            error = Z95 * np.sqrt(max(var, 0.0))
            rows.append(
                {
                    "level": band,
                    "part": part,
                    "relativity": float(np.exp(diff)),
                    "lower_95": float(np.exp(diff - error)),
                    "upper_95": float(np.exp(diff + error)),
                }
            )
    return pd.DataFrame(rows)


def add_presentation(
    table: pd.DataFrame, age_reference: str, rebased: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Add presentation columns, with age rebased to `age_reference` and others unchanged.

    The technical reference level of age is the band with the most exposure overall. For
    presentation the age relativities are divided by that of the adult band with the most
    exposure. The rebasing changes how the table reads and not the model. The bounds for age in
    `presentation_lower_95` and `presentation_upper_95` are those of the ratio to the presentation
    band when `rebased` (from `rebased_age_table`, for this part) is given, and are empty
    otherwise. The bounds in `lower_95` and `upper_95` stay on the technical reference.
    """
    out = table.copy()
    scale = float(
        out.loc[(out["factor"] == "age") & (out["level"] == age_reference), "relativity"].iloc[0]
    )
    is_age = out["factor"] == "age"
    out["presentation_relativity"] = np.where(is_age, out["relativity"] / scale, out["relativity"])
    out["presentation_lower_95"] = np.where(is_age, np.nan, out["lower_95"])
    out["presentation_upper_95"] = np.where(is_age, np.nan, out["upper_95"])
    if rebased is not None:
        by_level = rebased.set_index("level")
        for column, source in (
            ("presentation_lower_95", "lower_95"),
            ("presentation_upper_95", "upper_95"),
        ):
            mapped = out.loc[is_age, "level"].map(by_level[source])
            out.loc[is_age, column] = mapped.to_numpy()
    if "log_error" in out:
        out = out.drop(columns="log_error")
    return out[TABLE_COLUMNS]


def age_reference_for_presentation(raw: Frames) -> str:
    """The adult age band with the most train exposure, from the frames before grouping."""
    return levels.presentation_age_reference(raw, levels.decided_grouping(raw))


def base_rates(model: glm.TwoPartModel) -> pd.DataFrame:
    """The base value of each part for the reference profile of every factor."""
    return pd.DataFrame(
        {
            "component": ["frequency (claim hazard per exposure year)", "severity (dollars)"],
            "base_value": [
                float(np.exp(model.frequency.params["const"])),
                float(np.exp(model.severity.params["const"])),
            ],
        }
    )


def predict_from_relativities(
    profile: dict[str, str],
    exposure: float,
    frequency: pd.DataFrame,
    severity: pd.DataFrame,
    rates: pd.DataFrame,
    rebalance: float = 1.0,
    load: float = large_claims.PROVISIONAL_LOAD,
) -> float:
    """Expected annual cost from the base values and the relativities, with no model object.

    The frequency part is `1 - exp(-exposure * base * product of relativities)`, the severity part
    is `base * product of relativities`, and the cost is their product with the large-claim load
    and the rebalancing factor. Only rating factors in the profile are priced.
    """
    hazard, mean = float(rates["base_value"].iloc[0]), float(rates["base_value"].iloc[1])
    for factor, level in profile.items():
        for table, name in ((frequency, "hazard"), (severity, "mean")):
            line = table[(table["factor"] == factor) & (table["level"] == level)]
            value = float(line["relativity"].iloc[0]) if len(line) else 1.0
            if name == "hazard":
                hazard *= value
            else:
                mean *= value
    return float((1 - np.exp(-exposure * hazard)) * mean * (1 + load) * rebalance)


def save_table(table: pd.DataFrame, name: str, directory: Path = OUTPUT_DIR) -> Path:
    """Save a relativity table. It holds aggregates only."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    table.to_csv(path, index=False)
    return path
