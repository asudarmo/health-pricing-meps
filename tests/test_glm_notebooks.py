"""The GLM notebook and its summary run cleanly and agree with the saved tables (issue #35)."""

import json
import re
import time
from pathlib import Path

import duckdb
import nbformat
import pandas as pd
import pytest
from nbclient import NotebookClient

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import comparison as comparison_names
from health_pricing.models import figures, summary

REPO = Path(__file__).resolve().parents[1]
FULL = REPO / "notebooks" / "03_glm.ipynb"
SUMMARY = REPO / "notebooks" / "03_glm_summary.ipynb"
PERSON_LEVEL_NAMES = ("DUPERSID", "DUID", "VARSTR", "VARPSU")
SECTIONS = [
    "## Overview",
    "## Key decisions and findings",
    "## Data and metrics",
    "## Benefit types",
    "## Leakage check on the unknown level",
    "## Rating-factor levels",
    "## Large claims",
    "## Candidate (a)",
    "## Candidate (b)",
    "## Candidate (c)",
    "## Model comparison",
    "## Permitted rating factors",
    "## Smoking check",
    "## Diagnostics of the final structure",
    "## Relativities of the final structure",
    "## Age curve",
    "## Final tariff",
    "## Limitations",
]


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'mart_person_year_benefit'"
        ).fetchone()
        return row[0] == 1
    finally:
        con.close()


def _text(notebook, kind):
    return "\n".join(c.source for c in notebook.cells if c.cell_type == kind)


def _outputs_text(notebook) -> str:
    return json.dumps([c.get("outputs", []) for c in notebook.cells if c.cell_type == "code"])


def _slug(heading: str) -> str:
    text = re.sub(r"[^a-z0-9 \-]", "", heading.lower().lstrip("#").strip())
    return text.replace(" ", "-")


def _run(path: Path) -> nbformat.NotebookNode:
    notebook = nbformat.read(path, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    NotebookClient(
        notebook,
        timeout=1200,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
    ).execute()
    return notebook


@pytest.mark.parametrize("path", [FULL, SUMMARY])
def test_notebooks_define_no_functions_classes_or_lambdas_and_import_the_package(path):
    notebook = nbformat.read(path, as_version=4)
    code = _text(notebook, "code")
    assert "health_pricing" in code
    for banned in ("def ", "class ", "lambda"):
        assert banned not in code, banned


@pytest.mark.parametrize("path", [FULL, SUMMARY])
def test_the_saved_outputs_hold_no_person_level_names_or_local_paths(path):
    notebook = nbformat.read(path, as_version=4)
    outputs = _outputs_text(notebook)
    for name in PERSON_LEVEL_NAMES:
        assert name not in outputs, name
    assert "Users\\\\ardih" not in outputs and "C:\\\\Users" not in outputs


def test_the_full_notebook_has_every_section_in_order():
    notebook = nbformat.read(FULL, as_version=4)
    headings = [
        line for c in notebook.cells if c.cell_type == "markdown" for line in c.source.split("\n")
    ]
    position = -1
    for section in SECTIONS:
        found = [i for i, line in enumerate(headings) if line.startswith(section)]
        assert found, section
        assert found[0] > position, f"{section} is out of order"
        position = found[0]


def test_every_link_in_the_overview_points_to_a_heading():
    notebook = nbformat.read(FULL, as_version=4)
    markdown = _text(notebook, "markdown")
    slugs = {
        _slug(line)
        for c in notebook.cells
        if c.cell_type == "markdown"
        for line in c.source.split("\n")
        if line.startswith("#")
    }
    links = re.findall(r"\]\(#([^)]+)\)", markdown)
    assert len(links) >= 15
    missing = sorted(set(links) - slugs)
    assert not missing, missing
    assert "../_docs/data-flow.md" in markdown
    assert (REPO / "_docs" / "data-flow.md").exists()
    assert "mermaid" not in markdown.lower() and "```mermaid" not in markdown


def test_the_headline_numbers_equal_the_saved_tables():
    table = summary.headline_numbers().set_index("number")["value"]
    comparison = summary.read("model_comparison.csv")
    test = comparison[comparison["split"] == "test"].set_index("candidate")
    assert (
        table["Baseline test deviance (p = 1.5)"]
        == f"{test.loc[comparison_names.BASELINE, 'tweedie_deviance']:,.0f}"
    )
    assert (
        table["(a) Binomial-cloglog × Gamma, all factors, test Gini"]
        == f"{test.loc[comparison_names.NAME_A, 'gini']:.3f}"
    )
    surrogate_row = test.loc[comparison_names.NAME_A_SURROGATE]
    baseline_deviance = test.loc[comparison_names.BASELINE, "tweedie_deviance"]
    reduction = 100 * (1 - surrogate_row["tweedie_deviance"] / baseline_deviance)
    assert table["(a) Surrogate model (tariff), test deviance"] == (
        f"{surrogate_row['tweedie_deviance']:,.0f} ({reduction:.1f} percent below the baseline)"
    )
    assert surrogate_row["deviance_reduction_pct"] == pytest.approx(reduction)
    final = summary.read("final_scores.csv").set_index(["candidate", "split"])
    tariff_deviance = final.loc[("final_tariff", "test"), "tweedie_deviance"]
    assert table["Final tariff, test deviance"].startswith(f"{tariff_deviance:,.0f} (")
    assert final.loc[("final_tariff", "test"), "deviance_reduction_pct"] == pytest.approx(
        100 * (1 - tariff_deviance / baseline_deviance)
    )
    assert table["Final tariff, parameters"] == str(
        int(final.loc[("final_tariff", "test"), "parameters"])
    )
    options = summary.read("permitted_factor_options.csv").set_index(["candidate", "split"])
    assert table["(a) Final structure (9 factors), test Gini"] == (
        f"{options.loc[('final', 'test'), 'gini']:.3f}"
    )
    assert options.loc[("final", "test"), "rating_factors"] == 9
    smoking = summary.read("smoking_with_and_without_flags.csv")
    daily = smoking[
        (smoking["model"] == "with condition flags") & (smoking["smoking"] == "every day")
    ]
    assert table["Smoking, daily, relativity"] == f"{daily['combined_relativity'].iloc[0]:.2f}"
    assert table["Large-claim cap"] == "100,000 dollars"


def test_the_headline_numbers_appear_in_the_full_notebook_text():
    notebook = nbformat.read(FULL, as_version=4)
    markdown = _text(notebook, "markdown")
    for _, row in summary.headline_numbers().iterrows():
        assert row["value"] in markdown, (row["number"], row["value"])


def test_every_saved_figure_exists_and_is_an_image():
    for name, _ in summary.FIGURES:
        path = figures.FIGURES_DIR / f"{name}.png"
        assert path.exists(), name
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_summary_notebook_loads_tables_and_never_fits_a_model():
    notebook = nbformat.read(SUMMARY, as_version=4)
    code = _text(notebook, "code")
    for banned in ("fit_", "load_frames", "duckdb", "glm.", "prepare_frames", "statsmodels"):
        assert banned not in code, banned
    assert "summary.headline_numbers()" in code
    markdown = _text(notebook, "markdown")
    for heading in ("## Key decisions and findings", "## Key charts", "## Limitations"):
        assert heading in markdown, heading
    assert "smoking" in markdown.lower() and "exercise" in markdown.lower()


def test_the_summary_runs_top_to_bottom_in_a_fresh_kernel_in_under_30_seconds():
    started = time.time()
    notebook = _run(SUMMARY)
    assert time.time() - started < 30
    outputs = _outputs_text(notebook)
    for name in PERSON_LEVEL_NAMES:
        assert name not in outputs
    images = outputs.count("image/png")
    assert 4 <= images <= 8
    for _, row in summary.headline_numbers().iterrows():
        assert row["value"] in outputs, (row["number"], row["value"])
    table = pd.read_csv(summary.OUTPUT_DIR / "relativities_tariff.csv")
    assert len(table) > 20


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_the_full_notebook_runs_top_to_bottom_in_a_fresh_kernel_with_no_person_level_output():
    notebook = _run(FULL)
    outputs = _outputs_text(notebook)
    for name in PERSON_LEVEL_NAMES:
        assert name not in outputs, name
    assert "Traceback" not in outputs


def _decision_rows(path):
    notebook = nbformat.read(path, as_version=4)
    cell = next(c.source for c in notebook.cells if c.source.startswith("## Key decisions"))
    rows = [line for line in cell.split(chr(10)) if line.startswith("|")]
    return [re.sub(r"\]\((03_glm\.ipynb)?#", "](#", line) for line in rows]


def test_the_summary_decisions_table_is_the_full_notebooks_table():
    assert _decision_rows(SUMMARY) == _decision_rows(FULL)
    markdown = _text(nbformat.read(SUMMARY, as_version=4), "markdown")
    assert "A shorter notebook" not in markdown


def test_the_specification_table_parameters_equal_the_saved_scores():
    notebook = nbformat.read(FULL, as_version=4)
    cell = next(c.source for c in notebook.cells if c.source.startswith("### Comparison of the"))
    rows = {
        line.split("|")[1].strip(): int(line.split("|")[-2])
        for line in cell.split(chr(10))
        if line.startswith("| (")
    }
    comparison = summary.read("model_comparison.csv")
    test = comparison[comparison["split"] == "test"].set_index("candidate")
    for name in (
        comparison_names.NAME_A,
        comparison_names.NAME_B,
        comparison_names.NAME_C,
        comparison_names.NAME_C_AGE,
        comparison_names.NAME_A_SURROGATE,
    ):
        assert rows[name] == int(test.loc[name, "parameters"]), name
    final = summary.read("final_scores.csv").set_index(["candidate", "split"])
    assert rows["(a) Final tariff"] == int(final.loc[("final_tariff", "test"), "parameters"])
    options = summary.read("permitted_factor_options.csv").set_index(["candidate", "split"])
    assert rows["(a) Final structure, 9 rating factors"] == int(
        options.loc[("final", "test"), "parameters"]
    )
    age = summary.read("age_curve_comparison.csv")
    spline = age[(age["spline"] == "spline with 4 df") & (age["model"] == "spline")]
    assert rows["(a) Final structure with a smooth age curve"] == int(spline["parameters"].iloc[0])


def test_the_model_specifications_section_defines_the_notation_and_every_model():
    notebook = nbformat.read(FULL, as_version=4)
    markdown = _text(notebook, "markdown")
    for heading in (
        "## Model specifications",
        "### (a) Binomial-cloglog × Gamma",
        "### (b) Poisson × Gamma",
        "### (c) Stacked by benefit type",
        "### (c) Stacked with age × benefit interaction",
        "### Final structure, the smooth age model and the surrogate model (tariff)",
        "### Comparison of the specifications",
        "### The yardstick",
    ):
        assert heading in markdown, heading
    for symbol in ("$t_i", "$N_i", "$S_i", "$C$", r"$\ell$", r"\text{cloglog}", "Tweedie deviance"):
        assert symbol in markdown, symbol
    # the section sits directly after Data and metrics and before the benefit types
    assert markdown.index("## Data and metrics") < markdown.index("## Model specifications")
    assert markdown.index("## Model specifications") < markdown.index("## Benefit types")
    assert not any(c.cell_type == "markdown" and not c.source.strip() for c in notebook.cells)
