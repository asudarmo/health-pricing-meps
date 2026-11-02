"""Check on the smoking relativity of the final structure (issue #40).

The final structure gives smokers a relativity below 1. This module refits the structure without the
condition flags to see whether the flags absorb the effect (a condition that smoking causes could
take the cost that smoking would otherwise carry), and compares crude and adjusted relativities by
broad age group for adults. All tables are aggregates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from health_pricing.models import factors, glm, relativities
from health_pricing.models.frame import Frames

SMOKING = "OFTSMK53"
NON_SMOKER = "3"
SMOKER_LEVELS = ("1", "2")
LEVEL_NAMES = {"1": "every day", "2": "some days", "any": "any smoker"}
# The check was run on the ten factors that passed the selection rule, with smoking a rating factor.
RATING_WITH_FLAGS = factors.RATING_AFTER_RULE
RATING_WITHOUT_FLAGS = [f for f in RATING_WITH_FLAGS if f not in factors.CONDITION_FLAGS]
CONTROLS = factors.controls_for("rule_selected")
# Broad groups of adults, as the lower and upper age of the five-year bands they hold.
BROAD_GROUPS = (("18-39", 18, 39), ("40-64", 40, 64), ("65+", 65, 200))


def band_start(band: str) -> int:
    """The first age of a five-year band label such as `05-14` or `80+`."""
    return int(str(band).split("-")[0].rstrip("+"))


def broad_group(band: str) -> str | None:
    """The broad adult group of an age band, or None for the child bands."""
    start = band_start(band)
    for name, low, high in BROAD_GROUPS:
        if low <= start <= high:
            return name
    return None


HEALTH_CONTROLS = ["rthlth", "mnhlth"]


def _fit(
    frame: pd.DataFrame, rating: list[str], controls: list[str] | None = None
) -> glm.TwoPartModel:
    controls = CONTROLS if controls is None else controls
    return factors.fit_option(frame, rating, controls)


def _smoking_rows(model: glm.TwoPartModel, train: pd.DataFrame, label: str) -> pd.DataFrame:
    frequency = relativities.component_table(model, train, "frequency")
    severity = relativities.component_table(model, train, "severity")
    combined = relativities.combined_table(frequency, severity)
    rows = []
    for level in SMOKER_LEVELS:
        parts = {}
        for name, table in (
            ("frequency", frequency),
            ("severity", severity),
            ("combined", combined),
        ):
            line = table[(table["factor"] == SMOKING) & (table["level"] == level)]
            parts[name] = line.iloc[0] if len(line) else None
        if parts["combined"] is None:
            continue
        rows.append(
            {
                "model": label,
                "smoking": LEVEL_NAMES[level],
                "frequency_relativity": parts["frequency"]["relativity"],
                "severity_relativity": parts["severity"]["relativity"],
                "combined_relativity": parts["combined"]["relativity"],
                "combined_lower_95": parts["combined"]["lower_95"],
                "combined_upper_95": parts["combined"]["upper_95"],
                "claimants": int(parts["combined"]["claimants"]),
            }
        )
    return pd.DataFrame(rows)


def with_and_without_flags(prepared: Frames) -> pd.DataFrame:
    """The smoking relativities of the final structure under three sets of adjusting factors.

    The sets are the final structure, the structure without the condition flags, and the structure
    without the condition flags and without the self-rated health controls. The last two ask
    whether illness absorbs the discount.

    The combined relativity is the product of the frequency and severity relativities. The bounds
    treat the two as independent, so they are approximate.
    """
    with_flags = _fit(prepared.train, RATING_WITH_FLAGS)
    without = _fit(prepared.train, RATING_WITHOUT_FLAGS)
    no_health_controls = [c for c in CONTROLS if c not in HEALTH_CONTROLS]
    without_health = _fit(prepared.train, RATING_WITHOUT_FLAGS, no_health_controls)
    return pd.concat(
        [
            _smoking_rows(with_flags, prepared.train, "with condition flags"),
            _smoking_rows(without, prepared.train, "without condition flags"),
            _smoking_rows(
                without_health, prepared.train, "without condition flags and self-rated health"
            ),
        ],
        ignore_index=True,
    )


def adults(frame: pd.DataFrame) -> pd.DataFrame:
    """Adult rows with their broad age group. Children are excluded."""
    group = frame["age"].astype(object).map(broad_group)
    return frame[group.notna()].assign(broad_group=group[group.notna()].to_numpy())


def crude_by_group(frame: pd.DataFrame) -> pd.DataFrame:
    """Smoking against not smoking by broad age group, before any adjustment.

    The relativities are the capped cost per exposure year, the claimant rate and the capped cost
    per claimant of the smoker level over those of non-smokers in the same age group. The `unknown`
    level, the people never asked, is left out.
    """
    data = adults(frame)
    data = data[data[SMOKING].astype(str).isin([*SMOKER_LEVELS, NON_SMOKER])].copy()
    data["claimant"] = (data["capped_cost"] > 0).astype(int)
    data["smoking"] = np.where(data[SMOKING].astype(str) == NON_SMOKER, "non-smoker", "smoker")
    for level, name in LEVEL_NAMES.items():
        if level in SMOKER_LEVELS:
            data.loc[data[SMOKING].astype(str) == level, "smoking"] = name
    rows = []
    for group, part in data.groupby("broad_group"):
        base = part[part["smoking"] == "non-smoker"]
        base_cost = base["capped_cost"].sum() / base["exposure"].sum()
        base_rate = base["claimant"].mean()
        base_severity = base.loc[base["claimant"] == 1, "capped_cost"].mean()
        levels_ = {name: part[part["smoking"] == name] for name in ("every day", "some days")}
        levels_["any smoker"] = part[part["smoking"] != "non-smoker"]
        for name, rows_ in levels_.items():
            if not len(rows_):
                continue
            claimants = rows_[rows_["claimant"] == 1]
            rows.append(
                {
                    "age_group": group,
                    "smoking": name,
                    "person_years": len(rows_),
                    "claimants": len(claimants),
                    "crude_cost_relativity": (
                        rows_["capped_cost"].sum() / rows_["exposure"].sum() / base_cost
                    ),
                    "crude_frequency_relativity": rows_["claimant"].mean() / base_rate,
                    "crude_severity_relativity": claimants["capped_cost"].mean() / base_severity,
                }
            )
    return pd.DataFrame(rows)


def rebase(part: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """Drop unused levels and make the level with the most exposure the reference.

    A subset of the data may not hold the usual reference level, for example children are not in
    an adult group, and a model without a reference level cannot be fitted.
    """
    out = part.copy()
    for name in names:
        out[name] = out[name].cat.remove_unused_categories()
        exposure = out.groupby(name, observed=True)["exposure"].sum()
        exposure = exposure.drop(labels=["unknown"], errors="ignore")
        reference = exposure.idxmax()
        others = [c for c in out[name].cat.categories if c != reference]
        out[name] = pd.Categorical(out[name].astype(object), categories=[reference, *others])
    return out


def adjusted_by_group(prepared: Frames) -> pd.DataFrame:
    """The smoking relativity fitted inside each broad age group, with and without the flags.

    The final structure is refitted on the adults of each group, so the relativity is adjusted for
    the other factors within the group. Children are excluded. A level that cannot be estimated in
    a small group is left out.
    """
    train = adults(prepared.train)
    rows = []
    for group, part in train.groupby("broad_group"):
        part = rebase(part.drop(columns="broad_group"), [*RATING_WITH_FLAGS, *CONTROLS])
        for label, rating in (
            ("with condition flags", RATING_WITH_FLAGS),
            ("without condition flags", RATING_WITHOUT_FLAGS),
        ):
            try:
                model = _fit(part, rating)
            except ValueError:
                continue
            table = _smoking_rows(model, part, label)
            table.insert(0, "age_group", group)
            rows.append(table)
    return pd.concat(rows, ignore_index=True)
