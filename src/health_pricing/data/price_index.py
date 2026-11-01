"""Scripted download of the PCE-Health price index for on-levelling (issue #16).

The index is BEA NIPA Table 2.5.4 ("Price Indexes for Personal Consumption Expenditures by
Function"), line 37 ("Health"), annual, 2017 = 100. The choice of index was decided at decision
gate 4 (see _docs/price-index.md). The BEA API needs a key. It is read from the BEA_API_KEY
environment variable (run with `uv run --env-file .env ...`) and is never printed, logged or saved.

Run: uv run --env-file .env python -m health_pricing.data.price_index
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests

REFERENCE_DIR = Path(__file__).resolve().parents[3] / "data" / "reference"
CSV_PATH = REFERENCE_DIR / "pce_health.csv"
META_PATH = REFERENCE_DIR / "pce_health.meta.json"

API_URL = "https://apps.bea.gov/api/data"
TABLE = "T20504"
LINE_NUMBER = "37"
PARAMS = {
    "method": "GetData",
    "DatasetName": "NIPA",
    "TableName": TABLE,
    "Frequency": "A",
    "Year": "ALL",
    "ResultFormat": "JSON",
}
COLUMNS = ["year", "series_code", "line_number", "line_description", "index_value"]


class PriceIndexError(RuntimeError):
    pass


def request_url_without_key() -> str:
    """The request as recorded in the metadata, with the key left out."""
    query = "&".join(f"{k}={v}" for k, v in PARAMS.items())
    return f"{API_URL}?UserID=<BEA_API_KEY>&{query}"


def _redact(text: str, key: str) -> str:
    return text.replace(key, "<BEA_API_KEY>") if key else text


def fetch_pce_health(api_key: str | None = None) -> pd.DataFrame:
    """Download the Health line of Table 2.5.4 as one row per year."""
    key = api_key or os.environ.get("BEA_API_KEY", "")
    if not key:
        raise PriceIndexError(
            "BEA_API_KEY is not set. Put it in .env and run with `uv run --env-file .env ...`."
        )
    try:
        response = requests.get(API_URL, params={"UserID": key, **PARAMS}, timeout=60)
        response.raise_for_status()
        body = response.json()["BEAAPI"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise PriceIndexError(_redact(f"BEA request failed: {exc}", key)) from None
    if "Error" in body.get("Results", {}) or "Error" in body:
        message = json.dumps(body.get("Results", {}).get("Error", body.get("Error")))
        raise PriceIndexError(_redact(f"BEA returned an error: {message}", key))

    rows = [
        {
            "year": int(row["TimePeriod"]),
            "series_code": row["SeriesCode"],
            "line_number": int(row["LineNumber"]),
            "line_description": row["LineDescription"],
            "index_value": float(row["DataValue"].replace(",", "")),
        }
        for row in body["Results"]["Data"]
        if row["LineNumber"] == LINE_NUMBER
    ]
    if not rows:
        raise PriceIndexError(f"no line {LINE_NUMBER} rows in table {TABLE}")
    frame = pd.DataFrame(rows, columns=COLUMNS).sort_values("year").reset_index(drop=True)
    if set(frame["line_description"]) != {"Health"}:
        raise PriceIndexError(f"line {LINE_NUMBER} is not Health: {set(frame['line_description'])}")
    return frame


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(frame: pd.DataFrame, csv_path: Path = CSV_PATH, meta_path: Path = META_PATH) -> dict:
    """Write the CSV and a metadata file holding its checksum, the request and the date."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False, lineterminator="\n")
    meta = {
        "source": "Bureau of Economic Analysis, NIPA Table 2.5.4, line 37 (Health)",
        "table_name": TABLE,
        "index": "Fisher price index, 2017 = 100, annual",
        "request_url": request_url_without_key(),
        "retrieved_on": dt.date.today().isoformat(),
        "file": csv_path.name,
        "sha256": sha256_of(csv_path),
        "years": [int(frame["year"].min()), int(frame["year"].max())],
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


if __name__ == "__main__":
    try:
        result = save(fetch_pce_health())
    except PriceIndexError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        f"saved {result['file']}, {result['years'][0]} to {result['years'][1]}, "
        f"sha256 {result['sha256']}"
    )
