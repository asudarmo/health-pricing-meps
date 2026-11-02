"""External utilization trend from the CMS Unified Rate Review public use file (M5, issue #43).

The forecast trend for the out-of-time test must be set without looking at 2023. The CMS Unified
Rate Review (URR) public use file for plan year 2023 holds the filings that US health insurers
made in 2022 for 2023 coverage. Worksheet I of each filing gives, for each benefit category, the
utilization trend that the insurer assumed from its experience period to the projection period.
For a filing with a calendar-year 2021 experience period and a projection that starts on 1 January
2023, the Year 1 trend runs from 2021 to 2022 and the Year 2 trend from 2022 to 2023. The Year 2
trend is therefore a forecast, made before 2023, of the change in utilization from 2022 to 2023.

The file is downloaded by a script with its address, size and checksum, so the figure is
reproducible. It is public data and is not committed.
Run: `uv run python -m health_pricing.data.urr`
"""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from health_pricing.data.download import RAW_DIR

URR_URL = "https://www.cms.gov/files/zip/2023-urr-puf.zip"
URR_SIZE = 9_755_168
URR_SHA256 = "e1eb4a1533c406a79245851b1e619fc56b087dd94f941f7379a767ba6f53caad"
URR_DIR = RAW_DIR / "urr"
URR_ZIP = URR_DIR / "2023-urr-puf.zip"
INNER_ZIP = "PY2023_PUF_20221027.zip"
WORKSHEET1 = "PY2023_WKSH1_PUF_20221027.csv"
SOURCE_NOTE = (
    "CMS Unified Rate Review public use file, plan year 2023 (filings made in 2022), Worksheet I, "
    "file PY2023_WKSH1_PUF_20221027.csv in the archive last updated by CMS on 1 November 2022"
)
EXPERIENCE_START = "01/01/2021"
PROJECTION_START = "01/01/2023"
QUANTILES = (0.25, 0.5, 0.75)


def download(destination: Path = URR_ZIP, force: bool = False) -> Path:
    """Download the archive if it is missing, and check its size and SHA-256 checksum."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if force or not destination.exists():
        response = requests.get(URR_URL, timeout=120)
        response.raise_for_status()
        destination.write_bytes(response.content)
    data = destination.read_bytes()
    if len(data) != URR_SIZE or hashlib.sha256(data).hexdigest() != URR_SHA256:
        raise ValueError(f"{destination} does not match the expected size and checksum")
    return destination


def read_worksheet1(archive: Path | None = None) -> pd.DataFrame:
    """Worksheet I of the plan year 2023 filings, one row per filing."""
    archive = download() if archive is None else archive
    outer = zipfile.ZipFile(archive)
    inner = zipfile.ZipFile(io.BytesIO(outer.read(INNER_ZIP)))
    return pd.read_csv(inner.open(WORKSHEET1), low_memory=False)


def weighted_quantile(values: pd.Series, weights: pd.Series, q: float) -> float:
    """The smallest value whose cumulative weight reaches the share `q` of the total weight."""
    order = np.argsort(values.to_numpy())
    cumulative = np.cumsum(weights.to_numpy()[order]) / weights.sum()
    return float(values.to_numpy()[order][np.searchsorted(cumulative, q)])


def forecast_filings(sheet: pd.DataFrame) -> pd.DataFrame:
    """Filings with a calendar-year 2021 experience period and a projection starting 1 January 2023.

    For these filings the Year 2 trend is the trend from 2022 to 2023. Filings with no member months
    are left out. A trend outside 0.5 to 2 is treated as missing when the quartiles are taken.
    """
    keep = (
        (sheet["EXP_BEG_DT"] == EXPERIENCE_START)
        & (sheet["PRJ_BEG_DT"] == PROJECTION_START)
        & (sheet["EXP_MM_WK1"] > 0)
    )
    return sheet[keep].copy()


def utilization_trends(sheet: pd.DataFrame, year: str = "YR2") -> pd.DataFrame:
    """Member-month weighted quartiles of the utilization trend, by market and benefit category.

    The trend is a factor (1.02 is a rise of 2 percent a year). `blend` weights the inpatient and
    outpatient trends of each filing by the shares of the two categories in its experience index
    rate. Quartiles are weighted by member months, so a large filing counts for more.
    """
    filings = forecast_filings(sheet)
    rows = []
    markets = {"all": filings}
    markets.update(
        {m.lower(): filings[filings["MARKET"] == m] for m in ("Individual", "Small Group")}
    )
    for market, frame in markets.items():
        inp, out = f"{year}_TRND_UTIL_INP", f"{year}_TRND_UTIL_OUT"
        valid = frame[(frame[inp].between(0.5, 2)) & (frame[out].between(0.5, 2))].copy()
        total = valid["EXP_IDX_RT_INP"] + valid["EXP_IDX_RT_OUT"]
        valid = valid[total > 0]
        share = valid["EXP_IDX_RT_INP"] / (valid["EXP_IDX_RT_INP"] + valid["EXP_IDX_RT_OUT"])
        valid["blend"] = share * valid[inp] + (1 - share) * valid[out]
        for category, column in (("inpatient", inp), ("outpatient", out), ("blend", "blend")):
            row = {
                "market": market,
                "category": category,
                "filings": len(valid),
                "member_months": float(valid["EXP_MM_WK1"].sum()),
            }
            for q in QUANTILES:
                row[f"p{int(q * 100)}"] = weighted_quantile(valid[column], valid["EXP_MM_WK1"], q)
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> int:
    path = download()
    print(f"{path} ({path.stat().st_size:,} bytes), checksum verified")
    print(utilization_trends(read_worksheet1(path)).round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
