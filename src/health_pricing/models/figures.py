"""Saving the key charts of the GLM notebook as image files.

The charts are saved in `outputs/m3_draft/figures/`, so that the summary notebook can show them
without refitting anything. A chart holds aggregates only.
"""

from __future__ import annotations

from pathlib import Path

from health_pricing.models import glm

FIGURES_DIR = glm.SCORES_DIR / "figures"
DPI = 130


def save_figure(figure, name: str, directory: Path = FIGURES_DIR) -> Path:
    """Save a matplotlib figure as `<name>.png` and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.png"
    figure.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    return path
