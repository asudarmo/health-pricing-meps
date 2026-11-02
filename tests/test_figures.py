"""Tests for saving figures (issue #35)."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from health_pricing.models import figures  # noqa: E402


def test_a_figure_is_saved_as_a_png_in_the_directory(tmp_path):
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    path = figures.save_figure(fig, "example", tmp_path / "figs")
    plt.close(fig)
    assert path == tmp_path / "figs" / "example.png"
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_default_directory_is_under_the_draft_outputs():
    assert figures.FIGURES_DIR.parts[-3:] == ("outputs", "m3_draft", "figures")
