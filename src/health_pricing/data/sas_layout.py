"""Parse AHRQ's SAS program-statement files to get each variable's fixed-width column position.

Column positions shift between years (confirmed for the condition-flag block between 2022 and
2023), so this parses the file AHRQ publishes rather than hardcoding positions by hand, which
would be both tedious and error-prone across roughly 1,400 variables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_INPUT_START_RE = re.compile(r"^\s*INPUT\s+@")
_FIELD_RE = re.compile(
    r"@(?P<start>\d+)\s+(?P<name>\S+)\s+(?P<dollar>\$)?(?P<width>\d+)\.(?P<decimals>\d+)"
)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    start: int  # 1-indexed column, as AHRQ documents it
    width: int
    decimals: int
    is_char: bool

    @property
    def colspec(self) -> tuple[int, int]:
        """0-indexed, half-open, for pandas.read_fwf."""
        return (self.start - 1, self.start - 1 + self.width)


def parse_layout(su_txt_path: Path) -> list[FieldSpec]:
    """Parse the INPUT statement block of an AHRQ SAS program-statement file.

    The block starts at a line matching "INPUT @...", one field per line, and ends at a line
    that is just ";". Confirmed against h239gsu.txt, h243su.txt and h251su.txt.
    """
    lines = Path(su_txt_path).read_text(encoding="latin-1").splitlines()
    start_idx = next(i for i, line in enumerate(lines) if _INPUT_START_RE.match(line))

    fields = []
    for line in lines[start_idx:]:
        if line.strip() == ";":
            break
        match = _FIELD_RE.search(line)
        if not match:
            continue
        fields.append(
            FieldSpec(
                name=match.group("name"),
                start=int(match.group("start")),
                width=int(match.group("width")),
                decimals=int(match.group("decimals")),
                is_char=match.group("dollar") is not None,
            )
        )
    if not fields:
        raise ValueError(f"{su_txt_path}: no fields parsed from the INPUT block")
    return fields


def read_fixed_width(dat_path: Path, fields: list[FieldSpec]) -> pd.DataFrame:
    """Read an AHRQ fixed-width ASCII file using a parsed layout.

    Reads every field as text first, then converts per-field, rather than letting pandas guess
    types from fixed-width data, so the result matches what the SAS INPUT statement would
    produce: character fields stay strings, numeric fields with decimals follow SAS's implied
    decimal convention (e.g. a "13.6" informat means a 13-character field holding a value scaled
    by 10^6, not a value with a literal decimal point in the text).
    """
    colspecs = [f.colspec for f in fields]
    names = [f.name for f in fields]
    df = pd.read_fwf(dat_path, colspecs=colspecs, names=names, encoding="latin-1", dtype=str)

    for f in fields:
        if f.is_char:
            continue
        numeric = pd.to_numeric(df[f.name].str.strip(), errors="coerce")
        df[f.name] = numeric / (10**f.decimals) if f.decimals else numeric.astype("Int64")
    return df
