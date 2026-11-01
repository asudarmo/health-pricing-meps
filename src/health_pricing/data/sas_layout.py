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


_FORMAT_ASSIGNMENT_RE = re.compile(r"^\s*(?:FORMAT\s+)?(\$?\w+)\s+(\$?\w+F)\.\s*$")
_VALUE_BLOCK_START_RE = re.compile(r"^VALUE\s+(\$?\w+)\s*$")
_NEGATIVE_CODE_RE = re.compile(r"^\s*(-\d+)\s*=")


def parse_variable_to_format(su_txt_path: Path) -> dict[str, str]:
    """Map each variable name to its SAS FORMAT name, from the FORMAT statement block."""
    mapping: dict[str, str] = {}
    for line in Path(su_txt_path).read_text(encoding="latin-1").splitlines():
        match = _FORMAT_ASSIGNMENT_RE.match(line)
        if match:
            mapping[match.group(1)] = match.group(2)
    return mapping


def parse_reserved_codes(su_txt_path: Path) -> dict[str, set[str]]:
    """Map each variable name to the set of reserved negative codes its VALUE statement lists.

    This replaces hand-written claims about which variables carry AGENTS.md's reserved-code
    convention (-1/-7/-8/-15), after three rounds of QA catching such claims wrong for a subset
    of variables. A variable absent from the result has no negative code in its VALUE block, or
    no VALUE block at all. Only covers the standard numeric convention, not a variable's own
    character reserved marker (e.g. FAMID's "'0' = NON-RESPONSE").
    """
    var_to_format = parse_variable_to_format(su_txt_path)
    format_to_var = {fmt: var for var, fmt in var_to_format.items()}

    result: dict[str, set[str]] = {}
    current_var: str | None = None
    for line in Path(su_txt_path).read_text(encoding="latin-1").splitlines():
        header = _VALUE_BLOCK_START_RE.match(line.strip())
        if header:
            current_var = format_to_var.get(header.group(1))
            continue
        if current_var is None:
            continue
        if line.strip() == ";":
            current_var = None
            continue
        negative = _NEGATIVE_CODE_RE.match(line)
        if negative:
            result.setdefault(current_var, set()).add(negative.group(1))
    return result


def extract_value_block(su_txt_path: Path, variable: str) -> str:
    """Return the raw text of one variable's own VALUE block, or "" if it has none.

    Scoped to a single variable's block, not a whole-file substring search, because the same
    coded-range text (e.g. a top-coding group label) can legitimately appear in several
    variables' blocks, QA round 4 found a top-coding test that would still pass even if the
    specific variable's own line were wrong, as long as some other variable in the file kept it.
    """
    var_to_format = parse_variable_to_format(su_txt_path)
    format_name = var_to_format.get(variable)
    if format_name is None:
        return ""

    lines: list[str] = []
    in_block = False
    for line in Path(su_txt_path).read_text(encoding="latin-1").splitlines():
        if not in_block:
            header = _VALUE_BLOCK_START_RE.match(line.strip())
            if header and header.group(1) == format_name:
                in_block = True
            continue
        if line.strip() == ";":
            break
        lines.append(line)
    return "\n".join(lines)


def read_fixed_width(dat_path: Path, fields: list[FieldSpec]) -> pd.DataFrame:
    """Read an AHRQ fixed-width ASCII file using a parsed layout.

    Reads every field as text first, then converts per-field, rather than letting pandas guess
    types from fixed-width data, so the result matches what the SAS INPUT statement would
    produce: character fields stay strings, numeric fields with decimals follow SAS's implied
    decimal convention (e.g. a "13.6" informat means a 13-character field holding a value scaled
    by 10^6 when the text has no decimal point, but a literal point in the text overrides this).
    """
    colspecs = [f.colspec for f in fields]
    names = [f.name for f in fields]
    df = pd.read_fwf(dat_path, colspecs=colspecs, names=names, encoding="latin-1", dtype=str)

    for f in fields:
        if f.is_char:
            continue
        text = df[f.name].str.strip()
        numeric = pd.to_numeric(text, errors="coerce")
        if not f.decimals:
            df[f.name] = numeric.astype("Int64")
            continue
        # As in SAS, a literal decimal point in the text overrides the implied decimals. AHRQ's
        # event files and weights are stored with literal points (e.g. "233.22" under 9.2).
        has_point = text.str.contains(".", regex=False, na=False)
        df[f.name] = numeric.where(has_point, numeric / (10**f.decimals))
    return df
