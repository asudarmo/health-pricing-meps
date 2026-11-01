"""Load MEPS raw ASCII files into DuckDB, using AHRQ's own SAS column layout for each file.

Run after download.py. Each manifest entry becomes one table under the `raw` schema in
data/interim/meps.duckdb, with every variable AHRQ publishes for that file, so dbt staging
models can select and rename just the variables the modelling table needs (that selection is a
later task, once the PMI-scope claim definition, decision gate 2, is decided).

Run: uv run python -m health_pricing.data.load
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb
import requests

from health_pricing.data.download import MANIFEST, RAW_DIR, RawFile
from health_pricing.data.sas_layout import parse_layout, read_fixed_width

INTERIM_DIR = RAW_DIR.parent / "interim"
DUCKDB_PATH = INTERIM_DIR / "meps.duckdb"
EXTRACT_DIR = RAW_DIR / "_extracted"
LAYOUT_URL_TEMPLATE = "https://meps.ahrq.gov/data_stats/download_data/pufs/{slug}/{slug}su.txt"


def _slug(raw_file: RawFile) -> str:
    """The AHRQ file slug (e.g. "h243", "h239g") from a manifest entry's URL."""
    return raw_file.url.rsplit("/", 2)[-2]


def _layout_path(raw_file: RawFile) -> Path:
    return RAW_DIR / f"{_slug(raw_file)}su.txt"


def fetch_layout(raw_file: RawFile, *, force: bool = False) -> Path:
    """Download the SAS program-statement file for one manifest entry, if not already present."""
    dest = _layout_path(raw_file)
    if dest.exists() and not force:
        return dest
    url = LAYOUT_URL_TEMPLATE.format(slug=_slug(raw_file))
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def extract_dat(raw_file: RawFile) -> Path:
    """Extract the single .dat file from a manifest entry's zip, if not already extracted."""
    with zipfile.ZipFile(raw_file.destination) as zf:
        dat_names = [n for n in zf.namelist() if n.lower().endswith(".dat")]
        if len(dat_names) != 1:
            raise ValueError(
                f"{raw_file.key}: expected one .dat file in the zip, found {dat_names}"
            )
        dat_name = dat_names[0]
        extracted_path = EXTRACT_DIR / dat_name
        if not extracted_path.exists():
            zf.extract(dat_name, path=EXTRACT_DIR)
    return extracted_path


def load_one(raw_file: RawFile, con: duckdb.DuckDBPyConnection) -> int:
    layout_path = fetch_layout(raw_file)
    fields = parse_layout(layout_path)
    dat_path = extract_dat(raw_file)
    df = read_fixed_width(dat_path, fields)

    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.register("df_view", df)
    try:
        con.execute(f"CREATE OR REPLACE TABLE raw.{raw_file.key} AS SELECT * FROM df_view")
    finally:
        con.unregister("df_view")
    row_count = con.execute(f"SELECT COUNT(*) FROM raw.{raw_file.key}").fetchone()[0]
    print(f"{raw_file.key}: loaded {row_count:,} rows, {len(fields)} columns")
    return row_count


def load_all() -> dict[str, int]:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        return {raw_file.key: load_one(raw_file, con) for raw_file in MANIFEST}
    finally:
        con.close()


if __name__ == "__main__":
    load_all()
