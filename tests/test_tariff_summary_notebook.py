"""The tariff summary notebook loads saved tables, never fits, and agrees with them (M6, #69)."""

import time
from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient

from health_pricing import tariff_summary

REPO = Path(__file__).resolve().parents[1]
SUMMARY = REPO / "notebooks" / "06_tariff_summary.ipynb"


def _text(notebook, kind):
    return "\n".join(c.source for c in notebook.cells if c.cell_type == kind)


def test_the_notebook_defines_nothing_and_never_fits_a_model():
    notebook = nbformat.read(SUMMARY, as_version=4)
    code = _text(notebook, "code")
    assert "tariff_summary.headline_numbers()" in code
    for banned in (
        "def ",
        "class ",
        "lambda",
        "fit_",
        "freeze",
        "load_frames",
        "duckdb",
        "glm.",
        "statsmodels",
    ):
        assert banned not in code, banned
    markdown = _text(notebook, "markdown")
    for heading in (
        "## The relativities",
        "## The age curve before and after the monotone rule",
        "## Example quotes from the rating engine",
        "## A rate-change scenario",
        "## The pound scaling",
        "## Limitations",
    ):
        assert heading in markdown, heading
    assert r"\text{premium}" in markdown
    assert "risk premium (expected claims cost), illustrative £" in markdown
    assert "regression baseline, provisional until M7" in markdown


def test_the_notebook_runs_in_a_fresh_kernel_in_under_30_seconds():
    notebook = nbformat.read(SUMMARY, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    start = time.time()
    NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(SUMMARY.parent)}},
    ).execute()
    assert time.time() - start < 30
    errors = [
        o
        for c in notebook.cells
        if c.cell_type == "code"
        for o in c.outputs
        if o.output_type == "error"
    ]
    assert not errors


def test_the_quoted_numbers_agree_with_the_saved_tables():
    markdown = _text(nbformat.read(SUMMARY, as_version=4), "markdown")
    numbers = tariff_summary.headline_numbers().set_index("number")["value"]
    assert numbers["Rating-period level factor"] == "1.080"
    assert "1.080" in markdown and "0.244" in markdown and "576 pounds" in markdown
    assert "2,358 dollars" in markdown and "0.963" in markdown and "364 rating cells" in markdown
    ages = tariff_summary.age_before_after().set_index("age_band")
    assert abs(ages.loc["80+", "published"] - 0.9625) < 1e-3
    assert (ages["published"].iloc[3:].diff().dropna() >= -1e-12).all()  # adults never fall
    book = pd.read_csv(REPO / "outputs" / "v1" / "in_force_book.csv")
    assert len(book) == 364
    gap = pd.read_csv(REPO / "outputs" / "m6_draft" / "final_tariff_approximation_summary.csv")
    test_age = gap[(gap["split"] == "test") & (gap["segment_type"] == "age band")]
    assert f"{100 * test_age['max_abs_departure_final'].iloc[0]:.1f} percent" in markdown


def test_every_example_quote_matches_its_golden_case():
    table = tariff_summary.quote_summary(tariff_summary.example_quotes())
    assert len(table) == 4 and table["matches_golden_case"].all()
