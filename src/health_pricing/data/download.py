"""Scripted download of MEPS raw files, so the pipeline is reproducible from a clean clone.

Each entry in MANIFEST is one AHRQ public use file (ASCII, zipped). The expected size is the
exact Content-Length AHRQ serves, checked with a HEAD request before accepting a prior download
and after completing a new one. AHRQ does not publish checksums for these files, so file size is
the integrity check (see AGENTS.md: "URL + expected file size or checksum").

Run: uv run python -m health_pricing.data.download
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import requests

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"


@dataclass(frozen=True)
class RawFile:
    key: str
    hc_number: str
    url: str
    expected_size: int

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]

    @property
    def destination(self) -> Path:
        return RAW_DIR / self.filename


MANIFEST: list[RawFile] = [
    RawFile(
        "fyc_2022",
        "HC-243",
        "https://meps.ahrq.gov/data_files/pufs/h243/h243dat.zip",
        6_123_666,
    ),
    RawFile(
        "fyc_2023",
        "HC-251",
        "https://meps.ahrq.gov/data_files/pufs/h251/h251dat.zip",
        5_037_048,
    ),
    RawFile(
        "office_based_2022",
        "HC-239G",
        "https://meps.ahrq.gov/data_files/pufs/h239g/h239gdat.zip",
        2_320_565,
    ),
    RawFile(
        "office_based_2023",
        "HC-248G",
        "https://meps.ahrq.gov/data_files/pufs/h248g/h248gdat.zip",
        2_033_399,
    ),
    RawFile(
        "outpatient_2022",
        "HC-239F",
        "https://meps.ahrq.gov/data_files/pufs/h239f/h239fdat.zip",
        674_366,
    ),
    RawFile(
        "outpatient_2023",
        "HC-248F",
        "https://meps.ahrq.gov/data_files/pufs/h248f/h248fdat.zip",
        590_921,
    ),
    RawFile(
        "inpatient_2022",
        "HC-239D",
        "https://meps.ahrq.gov/data_files/pufs/h239d/h239ddat.zip",
        110_375,
    ),
    RawFile(
        "inpatient_2023",
        "HC-248D",
        "https://meps.ahrq.gov/data_files/pufs/h248d/h248ddat.zip",
        105_832,
    ),
]


# AHRQ codebooks (PDF, with unweighted frequencies for every variable). Kept apart from MANIFEST,
# which the loader reads to build the raw tables. Used by the codebook count tests (issue #20).
CODEBOOKS: list[RawFile] = [
    RawFile(
        "codebook_2022",
        "HC-243",
        "https://meps.ahrq.gov/data_stats/download_data/pufs/h243/h243cb.pdf",
        3_527_542,
    ),
    RawFile(
        "codebook_2023",
        "HC-251",
        "https://meps.ahrq.gov/data_stats/download_data/pufs/h251/h251cb.pdf",
        3_459_840,
    ),
]


class DownloadSizeError(RuntimeError):
    pass


def download_one(raw_file: RawFile, *, force: bool = False) -> Path:
    """Download one manifest entry to data/raw/, verifying its size. Skips if already present
    and correctly sized, unless force is set."""
    destination = raw_file.destination
    if destination.exists() and not force:
        actual = destination.stat().st_size
        if actual == raw_file.expected_size:
            print(f"{raw_file.key}: already downloaded, size OK ({actual:,} bytes)")
            return destination
        raise DownloadSizeError(
            f"{raw_file.key}: {destination} exists but is {actual:,} bytes, "
            f"expected {raw_file.expected_size:,}. Remove it and retry, or pass force=True."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(destination.suffix + ".part")

    with requests.get(raw_file.url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)

    actual = tmp_path.stat().st_size
    if actual != raw_file.expected_size:
        tmp_path.unlink(missing_ok=True)
        raise DownloadSizeError(
            f"{raw_file.key}: downloaded {actual:,} bytes from {raw_file.url}, "
            f"expected {raw_file.expected_size:,}. AHRQ may have revised the file, check "
            f"_docs/variable-mapping.md and update the manifest if so."
        )

    tmp_path.replace(destination)
    print(f"{raw_file.key}: downloaded, size OK ({actual:,} bytes)")
    return destination


def download_all(*, force: bool = False) -> list[Path]:
    return [download_one(raw_file, force=force) for raw_file in [*MANIFEST, *CODEBOOKS]]


if __name__ == "__main__":
    try:
        download_all()
    except DownloadSizeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
