"""Render the Mermaid diagrams of _docs/data-flow.md to SVG.

Each block is sent once to the mermaid.ink service. The SVG is saved with a hash of the block's
source, so a test can tell when a diagram was changed and not re-rendered.
Run with: uv run python -m health_pricing.diagrams
"""

import base64
import hashlib
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "_docs" / "data-flow.md"
DIAGRAM_DIR = ROOT / "outputs" / "figures" / "diagrams"
RENDER_URL = "https://mermaid.ink/svg/"
TIMEOUT_SECONDS = 60

_HEADING = re.compile(r"^#{2,3} (\d+[a-z]?)\.")
_BLOCK = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def extract_blocks(markdown: str) -> dict[str, str]:
    """Mermaid sources keyed by the number of the heading above them, such as '1' or '5a'."""
    blocks: dict[str, str] = {}
    heading = None
    in_block = False
    lines: list[str] = []
    for line in markdown.splitlines():
        if in_block:
            if line.strip() == "```":
                if heading is None or heading in blocks:
                    raise ValueError(f"Mermaid block without a unique heading number: {heading}")
                blocks[heading] = "\n".join(lines) + "\n"
                in_block = False
            else:
                lines.append(line)
        elif line.strip() == "```mermaid":
            in_block, lines = True, []
        elif match := _HEADING.match(line):
            heading = match.group(1)
    return blocks


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def svg_path(name: str, directory: Path = DIAGRAM_DIR) -> Path:
    return directory / f"diagram_{name}.svg"


def hash_path(name: str, directory: Path = DIAGRAM_DIR) -> Path:
    return directory / f"diagram_{name}.sha256"


def render(source: str) -> bytes:
    """The SVG for one Mermaid source, from mermaid.ink."""
    encoded = base64.urlsafe_b64encode(source.encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        RENDER_URL + encoded, headers={"User-Agent": "health-pricing-diagrams/1.0"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        svg = response.read()
    if b"<svg" not in svg[:2000]:
        raise ValueError("mermaid.ink did not return an SVG")
    return svg


def render_all(
    source_file: Path = SOURCE, directory: Path = DIAGRAM_DIR, force: bool = False
) -> list[str]:
    """Render the blocks whose stored hash is missing or out of date. Returns the names rendered."""
    directory.mkdir(parents=True, exist_ok=True)
    rendered = []
    for name, source in extract_blocks(source_file.read_text(encoding="utf-8")).items():
        current = source_hash(source)
        stored = hash_path(name, directory)
        if not force and stored.exists() and stored.read_text().strip() == current:
            continue
        svg_path(name, directory).write_bytes(render(source))
        stored.write_text(current + "\n")
        rendered.append(name)
    return rendered


def stale(source_file: Path = SOURCE, directory: Path = DIAGRAM_DIR) -> list[str]:
    """Names of the blocks with no SVG, or whose stored hash differs from the current source."""
    out = []
    for name, source in extract_blocks(source_file.read_text(encoding="utf-8")).items():
        stored = hash_path(name, directory)
        ok = (
            svg_path(name, directory).exists()
            and stored.exists()
            and stored.read_text().strip() == source_hash(source)
        )
        if not ok:
            out.append(name)
    return out


if __name__ == "__main__":
    done = render_all()
    print("rendered:", ", ".join(done) if done else "none, all up to date")
