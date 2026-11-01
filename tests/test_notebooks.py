"""The EDA notebook runs top to bottom from a clean kernel and shows aggregates only (issue #21)."""

from pathlib import Path

import duckdb
import nbformat
import pytest
from nbclient import NotebookClient

from health_pricing.data.load import DUCKDB_PATH

REPO = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO / "notebooks" / "02_eda.ipynb"
PERSON_LEVEL_NAMES = ("DUPERSID", "DUID", "VARSTR", "VARPSU")


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'mart_person_year'"
        ).fetchone()
        return row[0] == 1
    finally:
        con.close()


def test_the_notebook_imports_from_the_package_and_defines_no_functions_or_classes():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code = "\n".join(c.source for c in notebook.cells if c.cell_type == "code")
    assert "from health_pricing import eda" in code
    assert "def " not in code
    assert "class " not in code
    assert "lambda" not in code


def test_every_required_item_has_a_section():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    text = "\n".join(c.source for c in notebook.cells if c.cell_type == "markdown").lower()
    for heading in (
        "## exposure",
        "## zero-claim share",
        "## frequency and severity by age band",
        "## frequency and severity by sex and region",
        "## frequency by condition flag",
        "## distribution of annual claim cost",
        "## train and test balance",
    ):
        assert heading in text, heading


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_the_notebook_runs_top_to_bottom_in_a_fresh_kernel_with_no_person_level_output(tmp_path):
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    client = NotebookClient(
        notebook, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(REPO)}}
    )
    client.execute()  # raises CellExecutionError if any cell fails

    images = 0
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        for output in cell.outputs:
            assert output.output_type != "error"
            if "data" in output:
                images += "image/png" in output.data
                text = output.data.get("text/html", "") + output.data.get("text/plain", "")
            else:
                text = output.get("text", "")
            assert not any(name in text for name in PERSON_LEVEL_NAMES)
    assert images >= 5  # the exposure, age, sex and region, condition and claim cost charts
