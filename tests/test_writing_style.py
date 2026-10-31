"""Enforce the prose rules in _docs/writing-style.md: no em dash, no semicolon.

Scans Markdown files (repo docs) and Markdown cells in notebooks. Code fences, inline code
spans, URLs and file paths are exempt per the style guide, so fenced/indented code blocks are
stripped before scanning. writing-style.md itself is excluded because it quotes the banned
characters as examples.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BANNED_CHARS = {"—": "em dash", ";": "semicolon"}

EXCLUDED_MARKDOWN = {REPO_ROOT / "_docs" / "writing-style.md"}
EXCLUDED_DIR_NAMES = {".venv", "node_modules", ".git", ".ruff_cache", ".pytest_cache"}


def _strip_code(markdown_text: str) -> str:
    text = re.sub(r"```.*?```", "", markdown_text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    return text


def _iter_markdown_files():
    for path in REPO_ROOT.rglob("*.md"):
        if path in EXCLUDED_MARKDOWN:
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        yield path


def _iter_notebook_markdown_cells():
    for path in REPO_ROOT.rglob("*.ipynb"):
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        notebook = json.loads(path.read_text(encoding="utf-8"))
        for index, cell in enumerate(notebook.get("cells", [])):
            if cell.get("cell_type") != "markdown":
                continue
            source = "".join(cell.get("source", []))
            yield path, index, source


@pytest.mark.parametrize(
    "path", list(_iter_markdown_files()), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_markdown_file_has_no_banned_characters(path: Path):
    text = _strip_code(path.read_text(encoding="utf-8"))
    rel = path.relative_to(REPO_ROOT)
    for char, name in BANNED_CHARS.items():
        assert char not in text, f"{rel} contains a {name} ({char!r}) outside code"


@pytest.mark.parametrize(
    "path,index,source",
    list(_iter_notebook_markdown_cells()),
    ids=lambda v: str(v) if not isinstance(v, (Path, str)) else str(v),
)
def test_notebook_markdown_cell_has_no_banned_characters(path: Path, index: int, source: str):
    text = _strip_code(source)
    for char, name in BANNED_CHARS.items():
        assert char not in text, (
            f"{path.relative_to(REPO_ROOT)} cell {index} contains a {name} ({char!r}) outside code"
        )
