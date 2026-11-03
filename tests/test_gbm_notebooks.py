"""The GBM notebook and its summary run cleanly and agree with the saved tables (M4-lite)."""

import json
import time
from pathlib import Path

import duckdb
import nbformat
import pandas as pd
import pytest
from nbclient import NotebookClient

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import gbm, gbm_summary

REPO = Path(__file__).resolve().parents[1]
FULL = REPO / "notebooks" / "05_gbm.ipynb"
SUMMARY = REPO / "notebooks" / "05_gbm_summary.ipynb"
PERSON_LEVEL_NAMES = ("DUPERSID", "DUID", "VARSTR", "VARPSU")


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


def _run(path: Path) -> nbformat.NotebookNode:
    notebook = nbformat.read(path, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    NotebookClient(
        notebook,
        timeout=1800,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
    ).execute()
    return notebook


def _outputs(notebook) -> str:
    return json.dumps([c.get("outputs", []) for c in notebook.cells if c.cell_type == "code"])


@pytest.mark.parametrize("path", [FULL, SUMMARY])
def test_notebooks_define_nothing_and_call_the_package(path):
    code = _text(nbformat.read(path, as_version=4), "code")
    assert "health_pricing" in code
    for banned in ("def ", "class ", "lambda"):
        assert banned not in code, banned


@pytest.mark.parametrize("path", [FULL, SUMMARY])
def test_saved_outputs_hold_no_person_level_names_or_local_paths(path):
    outputs = _outputs(nbformat.read(path, as_version=4))
    for name in PERSON_LEVEL_NAMES:
        assert name not in outputs, name
    assert "Users\\ardih" not in outputs and "C:\\Users" not in outputs


def test_the_full_notebook_starts_with_a_summary_table_and_a_specification():
    markdown = _text(nbformat.read(FULL, as_version=4), "markdown")
    first = markdown.index("### Headline numbers")
    assert first < markdown.index("## Model specification") < markdown.index("## Tuning")
    for term in ("Tweedie", "init score", "monotone", "households"):
        assert term in markdown
    assert "## Decision gate" in markdown and "Decision (the user)" in markdown


def test_the_summary_never_fits_a_model_and_shows_the_headline_numbers():
    code = _text(nbformat.read(SUMMARY, as_version=4), "code")
    for banned in ("tune", "fit(", "freeze", "load_frames", "duckdb", "lightgbm", "shap."):
        assert banned not in code, banned
    assert "gbm_summary.headline_numbers()" in code


def test_the_summary_runs_in_a_fresh_kernel_in_under_30_seconds_and_matches_the_tables():
    started = time.time()
    notebook = _run(SUMMARY)
    assert time.time() - started < 30
    outputs = _outputs(notebook)
    assert "Traceback" not in outputs
    assert 3 <= outputs.count("image/png") <= 8
    for _, row in gbm_summary.headline_numbers().iterrows():
        assert row["value"] in outputs, row["number"]


def test_the_saved_tables_agree_with_each_other():
    scores = pd.read_csv(gbm.OUTPUT_DIR / "gbm_scores_2022.csv")
    test = scores[scores["split"] == "test"].set_index("candidate")
    gaps = pd.read_csv(gbm.OUTPUT_DIR / "gbm_deviance_gaps.csv").set_index(["first", "second"])
    gap = gaps.loc[(gbm.NAMES["glm_tariff"], gbm.NAMES["gbm"])]
    expected = (
        test.loc[gbm.NAMES["glm_tariff"], "tweedie_deviance"]
        - test.loc[gbm.NAMES["gbm"], "tweedie_deviance"]
    )
    assert gap["deviance_gap"] == pytest.approx(expected)
    grid = pd.read_csv(gbm.OUTPUT_DIR / "gbm_cv_grid.csv")
    assert len(grid) <= 12 and grid["chosen"].sum() == 1
    assert grid.loc[grid["chosen"], "cv_deviance_p1_5"].iloc[0] == grid["cv_deviance_p1_5"].min()


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_the_full_notebook_runs_top_to_bottom_in_a_fresh_kernel():
    outputs = _outputs(_run(FULL))
    for name in PERSON_LEVEL_NAMES:
        assert name not in outputs, name
    assert "Traceback" not in outputs
