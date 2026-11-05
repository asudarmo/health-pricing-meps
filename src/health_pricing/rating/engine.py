"""The rating engine (M6, issue #60).

`rate(profile, model_version)` prices a customer profile from the published tariff tables of a
model version, with no model object and no notebook. The premium is the base rate at the 2022
level times one relativity per rating factor, times the forecast trend and the rebase. The
large-claim load is already inside the base rate and the relativities, because the tariff is a
surrogate of the technical model that includes it. The tables are read from
`outputs/<model_version>/`: `relativities.csv`, `base_rate.csv` and,
once the scaling has been decided, `scaling.json`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

OUTPUTS = Path(__file__).resolve().parents[3] / "outputs"
RELATIVITIES = "relativities.csv"
BASE_RATE = "base_rate.csv"
SCALING = "scaling.json"
GBP_LABEL = "risk premium (expected claims cost), illustrative GBP, excluding expenses and margin"
AGE_RANGE = (0, 120)
# Fitted as controls and priced at their reference level, so a profile may carry them.
ANALYSIS_ONLY = {"rthlth", "mnhlth", "OFTSMK53", "PHYEXE53", "inscov"}
# Never permitted as rating factors.
NOT_PERMITTED = {"sex", "race", "income", "education"}
YES_NO = {"false": "0", "true": "1", "no": "0", "yes": "1"}


class ProfileError(ValueError):
    """The profile is not valid for rating."""


@dataclass
class Tariff:
    model_version: str
    relativities: pd.DataFrame
    base_rate_2022: float
    trend: float
    rebase: float
    scaling: dict | None = None
    age_bands: list[tuple[int, int, str]] = field(default_factory=list)

    def levels(self, factor: str) -> list[str]:
        return self.relativities.loc[self.relativities["factor"] == factor, "level"].tolist()

    @property
    def factors(self) -> list[str]:
        return list(dict.fromkeys(self.relativities["factor"]))


def _band_range(label: str) -> tuple[int, int]:
    low = int(re.match(r"\d+", label).group())
    high = AGE_RANGE[1] if label.endswith("+") else int(label.split("-")[1])
    return low, high


def load_tariff(model_version: str, directory: Path | None = None) -> Tariff:
    """Read a model version's tariff tables."""
    folder = (directory or OUTPUTS) / model_version
    if not (folder / RELATIVITIES).exists():
        raise FileNotFoundError(f"No tariff tables for model version '{model_version}' in {folder}")
    table = pd.read_csv(folder / RELATIVITIES, dtype={"level": str})
    base = pd.read_csv(folder / BASE_RATE).set_index("component")["value"]
    scaling = json.loads((folder / SCALING).read_text()) if (folder / SCALING).exists() else None
    bands = sorted(
        (*_band_range(label), label) for label in table.loc[table["factor"] == "age", "level"]
    )
    return Tariff(
        model_version,
        table,
        float(base["base rate at 2022 level"]),
        float(base["forecast trend"]),
        float(base["rebase"]),
        scaling,
        bands,
    )


def _check(tariff: Tariff, profile: dict) -> dict[str, str]:
    """The level of each rating factor, or an error that names the problem."""
    forbidden = sorted(NOT_PERMITTED & {str(k).lower() for k in profile})
    if forbidden:
        raise ProfileError(f"{', '.join(forbidden)} are not permitted rating factors")
    known = set(tariff.factors) | ANALYSIS_ONLY
    unknown = sorted(set(profile) - known)
    if unknown:
        raise ProfileError(f"Unknown profile fields: {', '.join(unknown)}")
    missing = [f for f in tariff.factors if f not in profile]
    if missing:
        raise ProfileError(f"Missing profile fields: {', '.join(missing)}")
    age = profile["age"]
    if isinstance(age, bool) or not isinstance(age, int | float) or age != int(age):
        raise ProfileError(f"age must be a whole number of years, got {age!r}")
    if not AGE_RANGE[0] <= age <= AGE_RANGE[1]:
        raise ProfileError(f"age must be between {AGE_RANGE[0]} and {AGE_RANGE[1]}, got {age}")
    chosen = {"age": next(label for low, high, label in tariff.age_bands if low <= age <= high)}
    for factor in tariff.factors:
        if factor == "age":
            continue
        allowed = tariff.levels(factor)
        value = str(profile[factor]).strip()
        if set(allowed) == {"0", "1"}:
            value = YES_NO.get(value.lower(), value)
        if value not in allowed:
            raise ProfileError(f"{factor}: '{profile[factor]}' is not a level. Allowed: {allowed}")
        chosen[factor] = value
    return chosen


def rate(
    profile: dict, model_version: str = "v1", tariff: Tariff | None = None, exposure: float = 1.0
) -> dict:
    """Price a profile. Returns the premium and a breakdown table.

    The premium is for `exposure` years, in dollars, with the rating-period level applied. If
    the model version has a scaling, the premium is also given as a risk premium (expected claims
    cost) in illustrative pounds, excluding expenses and margin, and the breakdown gains a last
    row for the scaling, so it then multiplies to the pound figure.
    """
    tariff = tariff or load_tariff(model_version)
    levels = _check(tariff, profile)
    table = tariff.relativities.set_index(["factor", "level"])["relativity"]
    rows = [{"step": "base rate at 2022 level", "level": "", "factor": tariff.base_rate_2022}]
    premium = tariff.base_rate_2022
    for factor, level in levels.items():
        value = float(table[(factor, level)])
        premium *= value
        rows.append({"step": factor, "level": level, "factor": value})
    for step, value in (("forecast trend", tariff.trend), ("rebase", tariff.rebase)):
        premium *= value
        rows.append({"step": step, "level": "", "factor": value})
    premium *= exposure
    result = {
        "model_version": tariff.model_version,
        "premium": premium,
        "exposure": exposure,
        "breakdown": pd.DataFrame(rows),
        "priced_at_reference": sorted(ANALYSIS_ONLY & set(profile)),
    }
    if tariff.scaling:
        factor = tariff.scaling["gbp_per_usd_premium"]
        result["premium_illustrative_gbp"] = premium * factor
        result["illustrative_label"] = GBP_LABEL
        result["illustrative"] = True
        result["breakdown"] = pd.concat(
            [
                result["breakdown"],
                pd.DataFrame([{"step": f"scaling to {GBP_LABEL}", "level": "", "factor": factor}]),
            ],
            ignore_index=True,
        )
    return result
