"""The monitoring summary notebook loads saved tables, never fits, and agrees with them (M5)."""

import json
import re
import time
from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient

from health_pricing.models import monitoring_summary

REPO = Path(__file__).resolve().parents[1]
SUMMARY = REPO / "notebooks" / "04_monitoring_summary.ipynb"
FULL = REPO / "notebooks" / "04_monitoring.ipynb"
PERSON_LEVEL_NAMES = ("DUPERSID", "DUID", "VARSTR", "VARPSU")


def _text(notebook, kind):
    return "\n".join(c.source for c in notebook.cells if c.cell_type == kind)


def _run(path: Path) -> nbformat.NotebookNode:
    notebook = nbformat.read(path, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    NotebookClient(
        notebook,
        timeout=300,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
    ).execute()
    return notebook


def test_the_summary_defines_nothing_and_never_fits_a_model():
    notebook = nbformat.read(SUMMARY, as_version=4)
    code = _text(notebook, "code")
    assert "health_pricing" in code and "monitoring_summary.headline_numbers()" in code
    for banned in (
        "def ",
        "class ",
        "lambda",
        "fit_",
        "freeze",
        "load_frames",
        "load_out_of_time",
        "duckdb",
        "glm.",
        "statsmodels",
    ):
        assert banned not in code, banned
    markdown = _text(notebook, "markdown")
    for heading in (
        "## Key decisions and findings",
        "## Decomposition and A/E equations",
        "## Key charts",
        "## Rebase decision",
        "## Limitations",
    ):
        assert heading in markdown, heading


def test_the_decisions_table_and_equations_are_those_of_the_full_notebook():
    def rows(path):
        notebook = nbformat.read(path, as_version=4)
        cell = next(c.source for c in notebook.cells if c.source.startswith("## Key decisions"))
        lines = [line for line in cell.split(chr(10)) if line.startswith("|")]
        return [re.sub(r"\]\((04_monitoring\.ipynb)?#", "](#", line) for line in lines]

    assert rows(SUMMARY) == rows(FULL)
    full = _text(nbformat.read(FULL, as_version=4), "markdown")
    summary = _text(nbformat.read(SUMMARY, as_version=4), "markdown")
    for equation in (r"\underbrace{M}_{\text{mix}}", r"\frac{F \times S \times L}{\tau}"):
        assert equation in full and equation in summary, equation


def test_the_summary_runs_in_a_fresh_kernel_in_under_30_seconds_and_matches_the_tables():
    started = time.time()
    notebook = _run(SUMMARY)
    assert time.time() - started < 30
    outputs = json.dumps([c.get("outputs", []) for c in notebook.cells if c.cell_type == "code"])
    for name in PERSON_LEVEL_NAMES:
        assert name not in outputs, name
    assert "Traceback" not in outputs
    assert 4 <= outputs.count("image/png") <= 8
    for _, row in monitoring_summary.headline_numbers().iterrows():
        assert row["value"] in outputs, (row["number"], row["value"])
    decision = pd.read_csv(monitoring_summary.OUTPUT_DIR / "rebase_decision_2023.csv").iloc[0]
    markdown = _text(nbformat.read(SUMMARY, as_version=4), "markdown")
    for value in (decision["decided_factor"], decision["lower_bound"], decision["upper_bound"]):
        assert (
            f"{value:.3g}" in markdown or f"{value:.3f}" in markdown or f"{value:.2f}" in markdown
        )
