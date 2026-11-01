"""Read unweighted value counts for chosen variables from an AHRQ MEPS codebook PDF.

The codebook prints one block per variable (Name, Description, ..., a table of Value, Unweighted
and Weighted columns, then a Total line). pypdf's layout mode keeps every row's label and numbers
on one line but returns the lines of a block bottom to top, so the Total line comes first and the
Name line last. This parser reads a page in that order. Every block is checked, the unweighted
counts must add up to the printed Total, so a mis-read row fails loudly instead of giving a wrong
expected count.
"""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

_ROW_RE = re.compile(r"^\s*(?P<label>\S.*?)\s{2,}(?P<unweighted>[\d,]+)\s+(?P<weighted>[\d,]+)\s*$")
_LEVEL_RE = re.compile(r"^(-?\d+(?:\s*-\s*\d+)?)\b")
_NAME_RE = re.compile(r"^\s*Name:\s+(\S+)\s*$")


class CodebookParseError(ValueError):
    pass


def level_key(label: str) -> str:
    """The code at the start of a value label, such as "-1", "2" or "0-4" (spaces removed)."""
    match = _LEVEL_RE.match(label.strip())
    if not match:
        raise CodebookParseError(f"no leading code in value label {label!r}")
    return re.sub(r"\s+", "", match.group(1))


def _to_int(text: str) -> int:
    return int(text.replace(",", ""))


def _parse_page(lines: list[str], wanted: set[str]) -> dict[str, dict[str, int]]:
    """Blocks on one page, bottom to top: Total, rows, Value header, End, Start, ..., Name."""
    found: dict[str, dict[str, int]] = {}
    rows: list[tuple[str, int]] = []
    total: int | None = None
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Total:"):
            numbers = re.findall(r"[\d,]{1,}", stripped.replace("Total:", ""))
            total = _to_int(numbers[0]) if numbers else None
            rows = []
            in_block = True
            continue
        name_match = _NAME_RE.match(line)
        if name_match:
            variable = name_match.group(1)
            if in_block and variable in wanted:
                counts = {level_key(label): count for label, count in rows}
                if len(counts) != len(rows):
                    raise CodebookParseError(f"{variable}: repeated value code in {rows}")
                if total is None or sum(counts.values()) != total:
                    raise CodebookParseError(
                        f"{variable}: counts add to {sum(counts.values())}, printed total {total}"
                    )
                found[variable] = counts
            in_block = False
            rows = []
            total = None
            continue
        if in_block and "Unweighted" not in line:
            row = _ROW_RE.match(line)
            if row and not row.group("label").startswith("Total"):
                rows.append((row.group("label"), _to_int(row.group("unweighted"))))
    return found


def read_counts(pdf_path: Path, variables: set[str]) -> dict[str, dict[str, int]]:
    """Unweighted count per value code for each requested variable, checked against its Total."""
    reader = PdfReader(str(pdf_path))
    remaining = set(variables)
    result: dict[str, dict[str, int]] = {}
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout") or ""
        if not any("Name:" in line for line in text.splitlines()):
            continue
        flat = re.sub(r"\s+", "", text)
        if not any(f"Name:{v}" in flat for v in remaining):
            continue
        found = _parse_page(text.splitlines(), remaining)
        result.update(found)
        remaining -= set(found)
        if not remaining:
            break
    if remaining:
        raise CodebookParseError(f"not found or not parsed in {pdf_path.name}: {sorted(remaining)}")
    return result
