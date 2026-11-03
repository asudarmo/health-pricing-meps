"""Headline numbers of the out-of-time test, read from the saved tables (M5, issue #50).

Every value is read from a table saved in `outputs/m5_draft/` by the monitoring notebook, and is
returned as text formatted as it appears in the notebook and the README. Nothing is refitted.
"""

from __future__ import annotations

import pandas as pd

from health_pricing.models import outofsample, recalibration

OUTPUT_DIR = outofsample.OUTPUT_DIR
FIGURES = [
    ("lift_2023", "Lift on 2023 with household bands"),
    ("relativity_stability_2023", "Relativities of 2023 against 2022"),
    ("age_curve_stability_2023", "Adult age curve, 2022 fit and 2023 refit"),
    ("drift_psi_2023", "PSI of the mix and of predicted cost"),
    ("trend_sensitivity_2023", "A/E by age group under the low, central and high trend"),
    ("er_stays_ae_by_age_group_2023", "A/E by age group with ER-originated stays added"),
]


FIGURES_DIR = OUTPUT_DIR / "figures"
SUMMARY_FIGURES = [
    ("gap_decomposition", "Decomposition of the rise in cost per exposure year"),
    ("ae_by_trend_option", "A/E on 2023 under each trend option"),
    ("lift_2023", "Lift on 2023 with household bands"),
    ("relativity_stability_2023", "Relativities of 2023 against 2022"),
    ("drift_psi_2023", "PSI of the mix and of predicted cost"),
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUTPUT_DIR / name)


def _interval(row: pd.Series) -> str:
    return f"{row['a_e']:.3f} ({row['lower_95']:.3f} to {row['upper_95']:.3f})"


def headline_numbers() -> pd.DataFrame:
    """The headline numbers as a table of label, text value and source file."""
    overall = read("ae_overall_2023.csv").set_index("model")
    scores = read("scores_2023.csv").set_index("candidate")
    gap = read("gap_decomposition.csv").set_index("component")
    joint = read("stability_joint_tests.csv").set_index("part")
    noise = read("stability_beyond_noise.csv")
    noise = noise[(noise["part"] == "combined") & (noise["role"] == "rating")].iloc[0]
    evidence = read("recalibration_evidence_2023.csv").set_index("evidence")["value"]
    outcome = read("recalibration_2023.csv").iloc[0]
    trends = read("trend_sensitivity_overall_2023.csv")
    trends = trends[trends["model"] == outofsample.TECHNICAL].set_index("scenario")
    er_overall = read("er_stays_ae_overall_2023.csv")
    er_overall = er_overall[er_overall["model"] == outofsample.TECHNICAL].set_index("definition")
    added = read("er_stays_added_by_age_group.csv")
    added = added[(added["year"] == 2023) & (added["age_group"] == "All")].iloc[0]
    psi = pd.concat([read("drift_psi_factors.csv"), read("drift_psi_predicted_cost.csv")])
    decided = recalibration.decided_rebase(float(overall.loc[outofsample.TECHNICAL, "a_e"]))
    rows = [
        (
            "A/E of the technical model on 2023, central forecast",
            _interval(overall.loc[outofsample.TECHNICAL]),
            "ae_overall_2023.csv",
        ),
        (
            "A/E of the tariff on 2023, central forecast",
            _interval(overall.loc[outofsample.TARIFF]),
            "ae_overall_2023.csv",
        ),
        (
            "Gini on 2023, technical model and tariff",
            f"{scores.loc[outofsample.TECHNICAL, 'gini']:.3f} and "
            f"{scores.loc[outofsample.TARIFF, 'gini']:.3f}",
            "scores_2023.csv",
        ),
        (
            "Rise in cost per exposure year, 2023 over 2022 train",
            f"{gap.loc['Total, cost per exposure year', 'change_percent']:.1f} percent",
            "gap_decomposition.csv",
        ),
        (
            "Severity beyond the price index",
            f"{gap.loc['Severity beyond the price index', 'change_percent']:.1f} percent "
            f"({gap.loc['Severity beyond the price index', 'lower_95_percent']:.1f} to "
            f"{gap.loc['Severity beyond the price index', 'upper_95_percent']:.1f})",
            "gap_decomposition.csv",
        ),
        (
            "Wald test that the relativities are unchanged, frequency and severity",
            f"p of {joint.loc['frequency', 'p_value']:.2f} and "
            f"{joint.loc['severity', 'p_value']:.2f}",
            "stability_joint_tests.csv",
        ),
        (
            "Rating levels whose relativity moved beyond noise",
            f"{int(noise['beyond_noise'])} of {int(noise['comparisons'])}",
            "stability_beyond_noise.csv",
        ),
        (
            "Rating levels off the book in the A/E",
            f"{int(evidence['off_book_levels'])} of {int(evidence['off_book_checked'])}",
            "recalibration_evidence_2023.csv",
        ),
        (
            "Largest PSI of any factor or of predicted cost",
            f"{psi['psi'].max():.4f}",
            "drift_psi_factors.csv, drift_psi_predicted_cost.csv",
        ),
        (
            "Rebase factor bounds on the forecast cost",
            f"{outcome['base_rate_factor_at_persistence_credibility']:.3f} and "
            f"{outcome['base_rate_factor_at_sampling_credibility']:.3f}",
            "recalibration_2023.csv",
        ),
        (
            "Rebase decided by the user",
            f"{decided['factor']:.2f}",
            "ae_overall_2023.csv, recalibration decision",
        ),
        (
            "A/E of the technical model at the low and high trend",
            f"{trends.loc['Low', 'a_e']:.3f} and {trends.loc['High', 'a_e']:.3f}",
            "trend_sensitivity_overall_2023.csv",
        ),
        (
            "Cost added by ER-originated stays in 2023",
            f"{added['cost_added_pct']:.1f} percent",
            "er_stays_added_by_age_group.csv",
        ),
        (
            "A/E with ER-originated stays, base model and refit",
            f"{er_overall.loc['With ER-originated stays', 'a_e']:.3f} and "
            f"{er_overall.loc['Refitted on broadened 2022 cost', 'a_e']:.3f}",
            "er_stays_ae_overall_2023.csv",
        ),
    ]
    return pd.DataFrame(rows, columns=["number", "value", "source"])


def headline(label: str) -> str:
    """One headline value as text, looked up by its label."""
    table = headline_numbers()
    return table.loc[table["number"] == label, "value"].iloc[0]


def rebase_decision() -> pd.DataFrame:
    """The decided rebase and its bounds, as saved by the monitoring notebook."""
    return read("rebase_decision_2023.csv")
