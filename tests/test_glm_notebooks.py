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
        == f"{test.loc['baseline', 'tweedie_deviance']:,.0f}"
    )
    assert table["Candidate (a), all factors, test Gini"] == f"{test.loc['a', 'gini']:.3f}"
    assert table["Surrogate model (tariff) of (a), test deviance"] == (
        f"{test.loc['a_surrogate', 'tweedie_deviance']:,.0f}"
    )
    final = summary.read("final_scores.csv").set_index(["candidate", "split"])
    assert table["Final tariff, test deviance"] == (
        f"{final.loc[('final_tariff', 'test'), 'tweedie_deviance']:,.0f}"
    )
    assert table["Final tariff, parameters"] == str(
        int(final.loc[("final_tariff", "test"), "parameters"])
    )
    options = summary.read("permitted_factor_options.csv").set_index(["candidate", "split"])
    assert table["Final structure (9 factors), test Gini"] == (
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
