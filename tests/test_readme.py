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
    split_labels = {
        "Wald test that the relativities are unchanged, frequency and severity",
        "A/E with ER-originated stays, base model and refit",
    }
    flat = " ".join(README.split())
    for label in quoted:
        value = table.set_index("number").loc[label, "value"]
        if label in split_labels:
            parts = value.replace("p of ", "").split(" and ")
            assert all(part in flat for part in parts), label
        else:
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


def test_the_model_specification_rows_are_rows_of_the_glm_notebook_table():
    import json

    cells = json.load(open(REPO / "notebooks" / "03_glm_summary.ipynb", encoding="utf-8"))["cells"]
    spec = next(
        "".join(c["source"])
        for c in cells
        if "".join(c["source"]).startswith("### Comparison of the specifications")
    )
    full = {line for line in spec.splitlines() if line.startswith("|")}
    rows = [line for line in README.splitlines() if line.startswith("| (a)")]
    assert len(rows) == 3
    for line in rows:
        assert line.rstrip() in full, line
    assert "| Model | Frequency part | Severity part |" in README
    for symbol in (r"$\ell$", r"$\rho$", "$r_0$", "$l_k(i)$"):
        assert symbol in README, symbol


def test_the_key_results_come_first_and_quote_the_saved_tables():
    headings = [line for line in README.splitlines() if line.startswith("#")]
    assert headings[0].startswith("# UK-style health insurance pricing on MEPS")
    assert headings[1] == "## Key results"
    section = README.split("## Key results")[1].split("\n## ")[0]
    flat = " ".join(section.split())
    m3 = summary.headline_numbers().set_index("number")["value"]
    m5 = monitoring_summary.headline_numbers().set_index("number")["value"]
    deviance = m3["Final tariff, test deviance"]
    assert deviance.split("(")[1].split(" percent")[0] + " percent below the baseline" in flat
    assert m3["Final tariff, test Gini"] in flat
    assert m5["A/E of the technical model on 2023, central forecast"].split(" ")[0] in flat
    assert m5["Rebase decided by the user"] in flat
    assert m3["Smoking, daily, relativity"] in flat
    assert m3["Exercise, raw gap in cost per exposure year"].replace(" percent", "") in flat
    assert m3["Exercise, adjusted frequency relativity"] in flat
    assert m3["Exercise, adjusted severity relativity"] in flat
    for word in ("DuckDB", "dbt", "statsmodels", "LightGBM", "SHAP", "pytest", "SQL", "Python"):
        assert word in flat, word


def test_how_this_was_built_links_the_process_documents():
    section = README.split("## How this was built")[1].split("\n## ")[0]
    for link in ("AGENTS.md", "_docs/process.md", "_docs/decisions.md"):
        assert link in section, link


def test_the_notebook_list_names_all_full_and_summary_notebooks():
    for name in (
        "03_glm.ipynb",
        "04_monitoring.ipynb",
        "05_gbm.ipynb",
        "03_glm_summary.ipynb",
        "04_monitoring_summary.ipynb",
        "05_gbm_summary.ipynb",
        "06_tariff_summary.ipynb",
    ):
        assert name in README, name


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


def test_the_v1_numbers_are_quoted_as_the_published_tables_have_them():
    import json

    flat = " ".join(README.split())
    meta = json.loads((REPO / "outputs" / "v1" / "model_version.json").read_text())
    test = meta["validation_metrics"]["test_split_2022"]
    assert f"deviance of {test['tweedie_deviance']:,.0f}" in flat
    assert f"Gini of {test['gini']:.3f}" in flat
    assert f"A/E is {meta['validation_metrics']['a_e_2023_after_rating_level']:.3f}" in flat
    totals = pd.read_csv(REPO / "outputs" / "v1" / "scenario_example_totals.csv")
    assert f"total premium rises {totals['change_pct'].iloc[0]:.1f} percent" in flat
    assert "regression baseline, provisional until M7" in flat
    assert "risk premium (expected claims cost), illustrative pounds" in flat


def test_the_zoomcamp_section_names_the_endpoints_and_says_not_yet_deployed():
    flat = " ".join(README.split())
    assert "## ML Zoomcamp: the pricing service" in README
    for endpoint in ("/health", "/quote", "/relativities", "/monitoring", "/scenario-impact"):
        assert endpoint in flat
    assert "not yet deployed" in flat and "gcloud run deploy" in flat
    assert "AI Dev Tools" in flat and "2 November 2026" in flat
    assert "_docs/openapi.json" in flat
