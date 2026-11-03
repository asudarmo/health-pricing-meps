"""The interim README quotes the saved tables and points to files that exist (M5, issue #51)."""

import re
from pathlib import Path

import pandas as pd

from health_pricing.models import monitoring_summary, outofsample, summary

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")
SECTIONS = [
    "## The problem",
    "## The data and the UK framing",
    "## Method",
    "## Results",
    "## Limitations",
    "## Roadmap (in progress)",
    "## Reproduce from a clean clone",
]


def _m3(label: str) -> str:
    table = summary.headline_numbers()
    table["number"] = table["number"].str.replace("×", "x")
    return table.set_index("number").loc[label, "value"]


def test_the_sections_are_present_in_order():
    headings = [line for line in README.splitlines() if line.startswith("## ")]
    positions = [headings.index(section) for section in SECTIONS]
    assert positions == sorted(positions)


def test_every_m5_headline_number_is_quoted_as_the_saved_table_has_it():
    table = monitoring_summary.headline_numbers()
    quoted = [
        "A/E of the technical model on 2023, central forecast",
        "A/E of the tariff on 2023, central forecast",
        "Gini on 2023, technical model and tariff",
        "Rise in cost per exposure year, 2023 over 2022 train",
        "Severity beyond the price index",
        "Wald test that the relativities are unchanged, frequency and severity",
        "Rating levels whose relativity moved beyond noise",
        "Largest PSI of any factor or of predicted cost",
        "Rebase decided by the user",
        "Rebase factor bounds on the forecast cost",
        "A/E of the technical model at the low and high trend",
        "Cost added by ER-originated stays in 2023",
        "A/E with ER-originated stays, base model and refit",
    ]
    for label in quoted:
        value = table.set_index("number").loc[label, "value"]
        assert value in README, label


def test_every_m3_headline_number_is_quoted_as_the_saved_table_has_it():
    quoted = [
        "Large-claim cap",
        "Claimants above the cap (train)",
        "Share of train cost above the cap",
        "Provisional large-claim load",
        "Smoking, daily, relativity",
        "Final tariff, parameters",
        "Final tariff, test deviance",
        "Final tariff, test Gini",
        "Final tariff, test A/E",
        "(a) Final structure (9 factors), test deviance",
        "(a) Final structure (9 factors), test Gini",
        "(a) Surrogate model (tariff), test deviance",
        "(b) Poisson x Gamma, test deviance",
    ]
    for label in quoted:
        value = _m3(label)
        assert value.split(" (")[0] in README, label


def test_the_model_specification_table_is_the_one_of_the_glm_notebook():
    import json

    cells = json.load(open(REPO / "notebooks" / "03_glm_summary.ipynb", encoding="utf-8"))["cells"]
    spec = next(
        "".join(c["source"])
        for c in cells
        if "".join(c["source"]).startswith("### Comparison of the specifications")
    )
    table = [line for line in spec.splitlines() if line.startswith("|")]
    assert table
    for line in table:
        assert line in README


def test_the_rebase_and_the_final_tariff_agree_with_the_saved_tables():
    decision = pd.read_csv(outofsample.OUTPUT_DIR / "rebase_decision_2023.csv").iloc[0]
    assert f"{decision['decided_factor']:.2f}" in README
    assert f"{decision['lower_bound']:.3f}" in README
    assert f"{decision['upper_bound']:.3f}" in README


def test_every_image_and_link_points_to_a_file_that_exists():
    targets = re.findall(r"\]\((?!http|#)([^)#]+)", README)
    assert targets
    for target in targets:
        assert (REPO / target).exists(), target


def test_the_readme_says_that_raw_and_person_level_data_are_not_in_the_repository():
    assert "Raw MEPS files and person-level data are not in the repository" in README
    assert "uv run python -m health_pricing.data.download" in README


def test_the_readme_links_the_summary_notebooks():
    assert "notebooks/04_monitoring_summary.ipynb" in README
    assert "notebooks/03_glm_summary.ipynb" in README


def test_the_gbm_numbers_are_quoted_as_the_saved_tables_have_them():
    from health_pricing.models import gbm_summary

    table = gbm_summary.headline_numbers().set_index("number")["value"]
    for label in ("GBM, test deviance", "GBM tariff, test deviance"):
        assert table[label].split(" (")[0] in README, label
    assert table["GLM tariff, test deviance"].split(" (")[0] in README
    assert table["GLM technical model, test deviance"].split(" (")[0] in README
    assert (
        "a Gini of 0.378 for both the GBM and the GLM tariff (0.386 for the technical model)"
        in " ".join(README.split())
    )
    assert "05_gbm_summary.ipynb" in README


def test_the_unconstrained_diagnostic_and_the_older_age_limitation_agree_with_saved_tables():
    from health_pricing.models import gbm

    flat = " ".join(README.split())
    free = pd.read_csv(gbm.OUTPUT_DIR / "gbm_unconstrained_scores.csv").set_index("candidate")
    row = free.loc["GBM, no age constraint (diagnostic)"]
    assert f"{row['tweedie_deviance']:,.0f}" in flat and f"{row['gini']:.3f}" in flat
    assert "The GLM tariff is the pricing basis" in flat
    assert "Done (lite)" in flat and "issue #57" in flat and "outputs/m6_draft/" in flat
    curve = pd.read_csv(outofsample.OUTPUT_DIR / "er_stays_age_curve.csv").set_index("age")
    for age in (80, 85):
        assert f"{curve.loc[age, 'relativity_broad']:.3f}" in flat
        assert f"{curve.loc[age, 'relativity_base']:.3f}" in flat
    assert ((curve["ratio_lower_95"] > 1) | (curve["ratio_upper_95"] < 1)).sum() == 0
    added = pd.read_csv(outofsample.OUTPUT_DIR / "er_stays_added_by_age_group.csv")
    added = added[added["year"] == 2023].set_index("age_group")["cost_added_pct"]
    assert f"{added['65+']:.1f}" in flat and f"{added['18-39']:.1f}" in flat
    tariff = pd.read_csv(REPO / "outputs" / "m3_draft" / "relativities_tariff.csv")
    age = tariff[tariff["factor"] == "age"].set_index("level")["presentation_relativity"]
    assert f"{age['80+']:.3f}" in flat
