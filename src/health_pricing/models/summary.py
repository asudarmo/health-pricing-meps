"""Headline numbers of the GLM work, read from the saved tables (issue #35).

The summary notebook shows these numbers and never refits a model. Every value is read from a
table saved in `outputs/m3_draft/` by the full notebook, so the summary cannot drift from it.
The numbers are returned as text, formatted as they appear in the notebooks.
"""

from __future__ import annotations

import pandas as pd

from health_pricing.models import comparison as names
from health_pricing.models import glm, large_claims

OUTPUT_DIR = glm.SCORES_DIR
FIGURES = [
    ("lift_candidates", "Lift of the candidates on the test split"),
    (
        "double_lift_surrogate",
        "Double lift of the surrogate model (tariff) against candidates (b) and (a)",
    ),
    ("lift_final_tariff", "Lift of the final tariff with household bands"),
    ("relativities_final", "Relativities of the final structure"),
    ("age_curve", "Smooth adult age curve and the tariff band relativities"),
    ("smoking_by_age_group", "Smoking relativity by adult age group"),
    ("exercise_insight", "Exercise: raw gap and adjusted effect"),
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUTPUT_DIR / name)


def _row(table: pd.DataFrame, **match) -> pd.Series:
    mask = pd.Series(True, index=table.index)
    for column, value in match.items():
        mask &= table[column] == value
    return table[mask].iloc[0]


def with_reduction(row: pd.Series) -> str:
    """A deviance with its percentage reduction against the baseline of the same split."""
    deviance, reduction = row["tweedie_deviance"], row["deviance_reduction_pct"]
    return f"{deviance:,.0f} ({reduction:.1f} percent below the baseline)"


def headline_numbers() -> pd.DataFrame:
    """The headline numbers as a table of label, text value and source file."""
    comparison = read("model_comparison.csv")
    options = read("permitted_factor_options.csv")
    final = read("final_scores.csv")
    check = read("final_tariff_overall_check.csv")
    caps = read("large_claim_caps.csv")
    smoking = read("smoking_with_and_without_flags.csv")
    exercise = read("exercise_unadjusted.csv")
    effect = read("exercise_adjusted.csv")

    def test(candidate):
        return _row(comparison, candidate=candidate, split="test")

    baseline, a, b = test(names.BASELINE), test(names.NAME_A), test(names.NAME_B)
    surrogate = test(names.NAME_A_SURROGATE)
    option = _row(options, candidate="final", split="test")
    tariff = _row(final, candidate="final_tariff", split="test")
    overall = _row(check, split="test")
    cap = _row(caps, cap="$100,000")
    daily = _row(smoking, model="with condition flags", smoking="every day")
    occasional = _row(smoking, model="with condition flags", smoking="some days")
    daily_no_health = _row(
        smoking, model="without condition flags and self-rated health", smoking="every day"
    )
    exercising = _row(exercise, PHYEXE53="1")
    not_exercising = _row(exercise, PHYEXE53="0")
    adjusted = effect[effect["level"].astype(str) == "0"].iloc[0]
    raw_gap = (
        not_exercising["capped_cost_per_exposure_year"]
        / exercising["capped_cost_per_exposure_year"]
    )
    rows = [
        (
            "Baseline test deviance (p = 1.5)",
            f"{baseline['tweedie_deviance']:,.0f}",
            "model_comparison.csv",
        ),
        (
            "(a) Binomial-cloglog × Gamma, all factors, test deviance",
            with_reduction(a),
            "model_comparison.csv",
        ),
        (
            "(a) Binomial-cloglog × Gamma, all factors, test Gini",
            f"{a['gini']:.3f}",
            "model_comparison.csv",
        ),
        ("(b) Poisson × Gamma, test deviance", with_reduction(b), "model_comparison.csv"),
        (
            "(a) Surrogate model (tariff), test deviance",
            with_reduction(surrogate),
            "model_comparison.csv",
        ),
        (
            "(a) Surrogate model (tariff), test Gini",
            f"{surrogate['gini']:.3f}",
            "model_comparison.csv",
        ),
        (
            "(a) Final structure (9 factors), test deviance",
            with_reduction(option),
            "permitted_factor_options.csv",
        ),
        (
            "(a) Final structure (9 factors), test Gini",
            f"{option['gini']:.3f}",
            "permitted_factor_options.csv",
        ),
        ("Final tariff, test deviance", with_reduction(tariff), "final_scores.csv"),
        ("Final tariff, test Gini", f"{tariff['gini']:.3f}", "final_scores.csv"),
        ("Final tariff, parameters", f"{int(tariff['parameters'])}", "final_scores.csv"),
        ("Final tariff, test A/E", f"{overall['a_e']:.3f}", "final_tariff_overall_check.csv"),
        (
            "Final tariff, test A/E band",
            f"{overall['lower_95']:.2f} to {overall['upper_95']:.2f}",
            "final_tariff_overall_check.csv",
        ),
        ("Large-claim cap", f"{large_claims.LARGE_CLAIM_CAP:,.0f} dollars", "large_claim_caps.csv"),
        (
            "Claimants above the cap (train)",
            f"{int(cap['claimants_above'])}",
            "large_claim_caps.csv",
        ),
        (
            "Share of train cost above the cap",
            f"{cap['share_of_cost_above_cap'] * 100:.1f} percent",
            "large_claim_caps.csv",
        ),
        (
            "Provisional large-claim load",
            f"{large_claims.PROVISIONAL_LOAD * 100:.1f} percent",
            "large_claims.py",
        ),
        (
            "Smoking, daily, relativity",
            f"{daily['combined_relativity']:.2f}",
            "smoking_with_and_without_flags.csv",
        ),
        (
            "Smoking, occasional, relativity",
            f"{occasional['combined_relativity']:.2f}",
            "smoking_with_and_without_flags.csv",
        ),
        (
            "Smoking, daily, without condition flags and self-rated health",
            f"{daily_no_health['combined_relativity']:.2f}",
            "smoking_with_and_without_flags.csv",
        ),
        (
            "Exercise, raw gap in cost per exposure year",
            f"{(raw_gap - 1) * 100:.0f} percent",
            "exercise_unadjusted.csv",
        ),
        (
            "Exercise, adjusted frequency relativity",
            f"{adjusted['frequency_relativity']:.2f}",
            "exercise_adjusted.csv",
        ),
        (
            "Exercise, adjusted severity relativity",
            f"{adjusted['severity_relativity']:.2f}",
            "exercise_adjusted.csv",
        ),
    ]
    return pd.DataFrame(rows, columns=["number", "value", "source"])


def headline(label: str) -> str:
    """One headline value as text, looked up by its label."""
    table = headline_numbers()
    return table.loc[table["number"] == label, "value"].iloc[0]
