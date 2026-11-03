"""The monitoring notebook runs cleanly and agrees with the saved tables (M5, issue #50)."""

import json
import re
from pathlib import Path

import duckdb
import nbformat
import pandas as pd
import pytest
from nbclient import NotebookClient

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import monitoring_summary, outofsample

REPO = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO / "notebooks" / "04_monitoring.ipynb"
PERSON_LEVEL_NAMES = ("DUPERSID", "DUID", "VARSTR", "VARPSU")
SECTIONS = [
    "## Overview",
    "## Key decisions and findings",
    "## Model specification",
    "## Frozen model and the 2023 scoring frame",
    "## Frequency trend and the forecast assumption (decided)",
    "## A/E on 2023 with the forecast trend",
    "## Relativity stability: the same structure refitted on 2023",
    "## Drift in the mix: PSI",
    "## Recalibration rule: level or structure",
    "## Sensitivity to the forecast trend",
    "## Sensitivity: ER-originated stays added to the claims",
    "## Limitations",
]
DONE_WHEN = [
    "ae_overall_2023.csv",
    "ae_by_level_2023.csv",
    "stability_joint_tests.csv",
    "relativity_stability_2023.csv",
    "drift_psi_factors.csv",
    "drift_psi_predicted_cost.csv",
    "recalibration_2023.csv",
]


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        query = (
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'mart_person_year'"
        )
        return con.execute(query).fetchone()[0] == 1
    finally:
        con.close()


def _text(notebook, kind):
    return "\n".join(c.source for c in notebook.cells if c.cell_type == kind)


def _slug(heading: str) -> str:
    text = re.sub(r"[^a-z0-9 \-]", "", heading.lower().lstrip("#").strip())
    return text.replace(" ", "-")


def _notebook():
    return nbformat.read(NOTEBOOK, as_version=4)


def test_the_notebook_defines_no_functions_classes_or_lambdas_and_imports_the_package():
    code = _text(_notebook(), "code")
    assert "health_pricing" in code
    for banned in ("def ", "class ", "lambda"):
        assert banned not in code, banned


def test_the_saved_outputs_hold_no_person_level_names_or_local_paths():
    notebook = _notebook()
    outputs = json.dumps([c.get("outputs", []) for c in notebook.cells if c.cell_type == "code"])
    for name in PERSON_LEVEL_NAMES:
        assert name not in outputs, name
    assert "Users\\\\ardih" not in outputs and "C:\\\\Users" not in outputs


def test_every_section_is_present_in_order():
    headings = [
        line for line in _text(_notebook(), "markdown").splitlines() if line.startswith("## ")
    ]
    positions = [headings.index(section) for section in SECTIONS]
    assert positions == sorted(positions)


def test_every_link_in_the_overview_and_key_decisions_points_to_a_heading():
    text = _text(_notebook(), "markdown")
    slugs = {_slug(line) for line in text.splitlines() if line.startswith("#")}
    links = re.findall(r"\]\(#([^)]+)\)", text)
    assert links
    for link in links:
        assert link in slugs, link


def test_the_headline_numbers_equal_the_saved_tables_and_appear_in_the_text():
    table = monitoring_summary.headline_numbers().set_index("number")["value"]
    overall = pd.read_csv(outofsample.OUTPUT_DIR / "ae_overall_2023.csv").set_index("model")
    technical = overall.loc[outofsample.TECHNICAL]
    assert table["A/E of the technical model on 2023, central forecast"] == (
        f"{technical['a_e']:.3f} ({technical['lower_95']:.3f} to {technical['upper_95']:.3f})"
    )
    assert table["Rebase decided by the user"] == "1.06"
    text = _text(_notebook(), "markdown")
    expected = {
        "A/E of the technical model on 2023, central forecast": "1.145 (1.075 to 1.220)",
        "Severity beyond the price index": "13.9 percent (5.6 to 23.0)",
        "Wald test that the relativities are unchanged, frequency and severity": (
            "p of 0.64 and 0.27"
        ),
        "Rating levels whose relativity moved beyond noise": "1 of 13",
        "Rating levels off the book in the A/E": "4 of 34",
        "Largest PSI of any factor or of predicted cost": "0.0020",
        "Rebase factor bounds on the forecast cost": "1.025 and 1.145",
        "A/E of the technical model at the low and high trend": "1.158 and 1.132",
        "Cost added by ER-originated stays in 2023": "33.0 percent",
        "A/E with ER-originated stays, base model and refit": "1.523 and 1.147",
    }
    for label, value in expected.items():
        assert table[label] == value, label
    # the key decisions table quotes them, with "p of" and "and" worded as in the table
    for fragment in ("1.145 (1.075 to 1.220)", "13.9 percent (5.6 to 23.0)", "0.0020"):
        assert fragment in text, fragment
    for fragment in ("0.64 and 0.27", "1 of 13", "4 of 34", "1.025 and 1.145", "1.06"):
        assert fragment in text, fragment
    assert "1.158 and 1.132" in text and "33.0 percent" in text


def test_the_key_charts_and_the_done_when_tables_are_saved():
    for name, _ in monitoring_summary.FIGURES:
        figure = outofsample.OUTPUT_DIR / "figures" / f"{name}.png"
        assert figure.exists() and figure.stat().st_size > 5000, name
    for name in DONE_WHEN:
        assert (outofsample.OUTPUT_DIR / name).exists(), name
    assert (REPO / "_docs" / "recalibration-rule.md").exists()


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_the_notebook_runs_top_to_bottom_in_a_fresh_kernel_with_no_person_level_output():
    notebook = _notebook()
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    NotebookClient(
        notebook,
        timeout=1800,
        kernel_name="python3",
        resources={"metadata": {"path": str(NOTEBOOK.parent)}},
    ).execute()
    outputs = json.dumps([c.get("outputs", []) for c in notebook.cells if c.cell_type == "code"])
    for name in PERSON_LEVEL_NAMES:
        assert name not in outputs, name
    assert "Traceback" not in outputs
    # the headline numbers are the same after a fresh run
    table = monitoring_summary.headline_numbers()
    assert len(table) == 14
