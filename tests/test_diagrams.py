"""Tests that the Mermaid diagrams of _docs/data-flow.md are rendered and current."""

from health_pricing import diagrams


def test_blocks_are_extracted_with_the_heading_number():
    markdown = (
        "## 1. A\n\n```mermaid\nflowchart TD\n  a --> b\n```\n\n### 2a. B\n\n```mermaid\nx\n```\n"
    )
    blocks = diagrams.extract_blocks(markdown)
    assert list(blocks) == ["1", "2a"]
    assert blocks["1"] == "flowchart TD\n  a --> b\n"


def test_the_hash_changes_when_the_source_changes():
    assert diagrams.source_hash("a\n") != diagrams.source_hash("b\n")


def test_stale_reports_a_missing_and_a_changed_diagram(tmp_path):
    source = tmp_path / "flow.md"
    source.write_text("## 1. A\n\n```mermaid\nx\n```\n", encoding="utf-8")
    assert diagrams.stale(source, tmp_path) == ["1"]
    diagrams.svg_path("1", tmp_path).write_text("<svg/>")
    diagrams.hash_path("1", tmp_path).write_text(diagrams.source_hash("x\n") + "\n")
    assert diagrams.stale(source, tmp_path) == []
    source.write_text("## 1. A\n\n```mermaid\ny\n```\n", encoding="utf-8")
    assert diagrams.stale(source, tmp_path) == ["1"]


def test_every_diagram_in_data_flow_is_rendered_and_current():
    assert diagrams.stale() == [], "run: uv run python -m health_pricing.diagrams"
