"""The recalibration rule: a change of level or a change of structure (M5, issue #47).

The rule reads the evidence of the core M5 tasks and recommends one of four actions: do nothing,
rebase (change the base rate), refit the relativities, or review the structure. It does not change
the model. The final refit is M6. The large-claim load is re-estimated in M6 and is handled apart,
so the rule works on the A/E with the provisional load as it stands and reports how much of the gap
is consistent with the load.

Thresholds are constants of this module. They are logged in `_docs/decisions.md` and written in
`_docs/recalibration-rule.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from health_pricing.models import drift, outofsample

ALPHA = 0.05  # a difference is beyond noise when its chance probability is below this
PSI_MIX = drift.BAND_LOW  # a PSI above this is a change of mix
RANKING_DROP = 0.05  # a fall in Gini of this much, against the 2022 test split, is a lost ranking
CREDIBILITY_P = 1.645  # normal point for a 90 percent probability
CREDIBILITY_K = 0.05  # within 5 percent of the true level

# The spread of the year-to-year change in level that the forecast allows: the quartiles of the CMS
# Unified Rate Review utilization trend (0.8 and 3.1 percent) read as a normal spread.
TREND_SPREAD = (0.031 - 0.008) / (2 * 0.6745)

DO_NOTHING = "Do nothing"
REBASE = "Rebase"
REFIT = "Refit the relativities"
REVIEW = "Review the structure"


@dataclass
class Evidence:
    """The numbers the rule reads. All are aggregates from the saved M5 tables."""

    a_e: float
    a_e_lower: float
    a_e_upper: float
    claimants: int  # claimants in the later year
    severity_cv2: float  # squared coefficient of variation of capped cost per claimant
    frequency_p: float  # Wald p-value that the frequency relativities are unchanged
    severity_p: float  # the same for severity
    levels_beyond_noise: int  # rating levels whose ratio of relativities excludes 1
    levels_compared: int
    off_book_levels: int  # rating levels whose relative A/E excludes 1
    off_book_checked: int  # rating levels with enough claimants
    max_psi: float  # the largest PSI of a rating factor or of predicted cost
    gini_later: float
    gini_earlier: float
    load_a_e_change: float = 0.0  # A/E points added by matching the load to the later year
    notes: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    action: str
    base_rate_factor: float  # multiplier on the forecast cost, at the sampling credibility
    credibility: float  # limited fluctuation credibility, which measures sampling error only
    persistence_credibility: float  # weight if the year-to-year spread is that of the trend
    lower_base_rate_factor: float  # multiplier at the persistence credibility
    reasons: list[str]
    checks: dict[str, bool]


def chance_probability(count: int, total: int, alpha: float = ALPHA) -> float:
    """The chance of `count` or more differences out of `total` when each has probability alpha."""
    return float(stats.binom.sf(count - 1, total, alpha)) if total else 1.0


def full_credibility_claims(cv2: float) -> float:
    """Claimants needed for full credibility of the level, from the limited fluctuation standard.

    Within `CREDIBILITY_K` of the true level with the probability of `CREDIBILITY_P`, for a claim
    count that is Poisson and a severity with a squared coefficient of variation of `cv2`.
    """
    return (CREDIBILITY_P / CREDIBILITY_K) ** 2 * (1 + cv2)


def credibility(claimants: int, cv2: float) -> float:
    """The square-root credibility of one year, which is at most 1."""
    return float(min(1.0, np.sqrt(claimants / full_credibility_claims(cv2))))


def persistence_credibility(evidence: Evidence, spread: float = TREND_SPREAD) -> float:
    """Weight on one year when the level may drift by `spread` from year to year.

    This is the Buhlmann form `spread^2 / (spread^2 + standard error^2)`. The standard error is that
    of the A/E, from its interval. Sampling error is not the only reason to doubt one year: the
    level of cost can also move and then move back. With two years of data the spread cannot be
    estimated from the data, so it is taken from the forecast and gives a lower bound.
    """
    error = (evidence.a_e_upper - evidence.a_e_lower) / (2 * 1.959963984540054)
    return float(spread**2 / (spread**2 + error**2))


def checks(evidence: Evidence) -> dict[str, bool]:
    """The four yes or no readings of the evidence."""
    return {
        "gap": evidence.a_e_lower > 1 or evidence.a_e_upper < 1,
        "structure_moved": (
            evidence.frequency_p < ALPHA
            or evidence.severity_p < ALPHA
            or chance_probability(evidence.levels_beyond_noise, evidence.levels_compared) < ALPHA
            or chance_probability(evidence.off_book_levels, evidence.off_book_checked) < ALPHA
        ),
        "mix_moved": evidence.max_psi > PSI_MIX,
        "ranking_lost": evidence.gini_earlier - evidence.gini_later > RANKING_DROP,
    }


def recommend(evidence: Evidence) -> Recommendation:
    """The action that the evidence supports, with the reasons in plain words."""
    flags = checks(evidence)
    z = credibility(evidence.claimants, evidence.severity_cv2)
    factor = 1 + z * (evidence.a_e - 1)
    zp = persistence_credibility(evidence)
    lower = 1 + zp * (evidence.a_e - 1)
    interval = f"{evidence.a_e_lower:.3f} to {evidence.a_e_upper:.3f}"
    reasons = [
        f"Overall A/E is {evidence.a_e:.3f} with an interval of {interval}, so "
        + ("the interval excludes 1." if flags["gap"] else "the interval contains 1.")
    ]
    if flags["structure_moved"]:
        reasons.append(
            "The relativities moved beyond noise: Wald p-values of "
            f"{evidence.frequency_p:.2f} (frequency) and {evidence.severity_p:.2f} (severity), "
            f"{evidence.levels_beyond_noise} of {evidence.levels_compared} rating levels beyond "
            f"noise and {evidence.off_book_levels} of {evidence.off_book_checked} off the book "
            "in the A/E."
        )
    else:
        reasons.append(
            "The relativities did not move beyond noise: Wald p-values of "
            f"{evidence.frequency_p:.2f} (frequency) and {evidence.severity_p:.2f} (severity), "
            f"{evidence.levels_beyond_noise} of {evidence.levels_compared} rating levels beyond "
            f"noise and {evidence.off_book_levels} of {evidence.off_book_checked} off the book "
            "in the A/E, none more than chance allows."
        )
    reasons.append(
        f"The largest PSI is {evidence.max_psi:.4f}, "
        + ("above" if flags["mix_moved"] else "below")
        + f" {PSI_MIX}, so the mix {'moved' if flags['mix_moved'] else 'did not move'}."
    )
    reasons.append(
        f"Gini is {evidence.gini_later:.3f} against {evidence.gini_earlier:.3f}, so the ranking "
        + ("fell." if flags["ranking_lost"] else "held.")
    )
    if flags["structure_moved"] and flags["ranking_lost"]:
        action = REVIEW
    elif flags["structure_moved"]:
        action = REFIT
    elif flags["gap"]:
        action = REBASE
    else:
        action = DO_NOTHING
    if action == REBASE:
        reasons.append(
            f"One year of {evidence.claimants:,} claimants has credibility {z:.2f} against a full "
            f"standard of {full_credibility_claims(evidence.severity_cv2):,.0f}, which covers "
            f"sampling error only. If the level can drift by as much as the forecast allows, the "
            f"weight on one year is {zp:.2f}. The base rate therefore moves by a factor between "
            f"{lower:.3f} and {factor:.3f} on the forecast cost, and the choice within that range "
            "is a judgement."
        )
    rebase = action == REBASE
    return Recommendation(
        action,
        factor if rebase else 1.0,
        z,
        zp,
        lower if rebase else 1.0,
        reasons,
        flags,
    )


def gather(oot: outofsample.OutOfTime, directory: Path = outofsample.OUTPUT_DIR) -> Evidence:
    """The evidence of the saved M5 tables for the tariff-side rule, with the technical model's A/E.

    The A/E is that of the technical model with the central forecast. The level checks use the
    tariff, which is what would be charged.
    """

    def read(name: str) -> pd.DataFrame:
        return pd.read_csv(directory / name)

    overall = read("ae_overall_2023.csv").set_index("model").loc[outofsample.TECHNICAL]
    joint = read("stability_joint_tests.csv").set_index("part")
    noise = read("stability_beyond_noise.csv")
    noise = noise[(noise["part"] == "combined") & (noise["role"] == "rating")].iloc[0]
    levels = read("ae_by_level_2023.csv")
    levels = levels[
        (levels["model"] == outofsample.TARIFF)
        & (levels["role"] == "rating")
        & levels["enough_claimants"]
    ]
    psi = pd.concat([read("drift_psi_factors.csv"), read("drift_psi_predicted_cost.csv")])
    psi = psi[psi["kind"].isin(["rating", "predicted_cost"])]
    scores = read("scores_2023.csv").set_index("candidate")
    earlier = read("frozen_model_scores_2022.csv")
    earlier = earlier[
        (earlier["candidate"] == outofsample.TECHNICAL) & (earlier["split"] == "test")
    ].iloc[0]
    load = read("load_check_2023.csv").iloc[0]
    claimed = oot.frame.loc[oot.frame["capped_cost"] > 0, "capped_cost"]
    return Evidence(
        a_e=float(overall["a_e"]),
        a_e_lower=float(overall["lower_95"]),
        a_e_upper=float(overall["upper_95"]),
        claimants=int(len(claimed)),
        severity_cv2=float(claimed.var(ddof=1) / claimed.mean() ** 2),
        frequency_p=float(joint.loc["frequency", "p_value"]),
        severity_p=float(joint.loc["severity", "p_value"]),
        levels_beyond_noise=int(noise["beyond_noise"]),
        levels_compared=int(noise["comparisons"]),
        off_book_levels=int((~levels["moves_with_the_book"].astype(bool)).sum()),
        off_book_checked=int(len(levels)),
        max_psi=float(psi["psi"].max()),
        gini_later=float(scores.loc[outofsample.TECHNICAL, "gini"]),
        gini_earlier=float(earlier["gini"]),
        load_a_e_change=float(load["change_in_a_e_points"]),
    )
