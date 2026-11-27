"""Read tools under a per-agent token budget (task 5.4)."""

from __future__ import annotations

import pytest

from stock_analyzer.config import Settings
from stock_analyzer.ingest.parse_md import parse_report
from stock_analyzer.ingest.structure import build_structure
from stock_analyzer.story.reading import ReadBudget, ReadRefused, ReportLibrary, read_paragraphs, read_section
from tests.conftest import fixture_text

SETTINGS = Settings(repeated_line_min_pages=999)


@pytest.fixture(scope="module")
def library() -> ReportLibrary:
    reports = {}
    for fy in (2023, 2024, 2025):
        parsed = parse_report(
            fixture_text(f"mltm_{fy}_business_slice.md"),
            ticker="MLTM",
            fiscal_year=fy,
            filing_id=fy,
            settings=SETTINGS,
        )
        reports[fy] = (parsed, build_structure(parsed, SETTINGS))
    return ReportLibrary(reports)


def test_read_section_labels_paragraphs_with_ids_and_pages(library):
    budget = ReadBudget(tokens=50_000, chars_per_token=3.0)
    text = read_section(library, budget, 2025, "business-19")
    assert text.startswith("[MLTM-2025-p") and "הליכים משפטיים" in text
    assert budget.spent == budget.estimate(text) > 0


def test_over_budget_read_is_refused_with_the_remaining_budget(library):
    budget = ReadBudget(tokens=100, chars_per_token=3.0)
    with pytest.raises(ReadRefused, match=r"only 100 of this agent's 100-token"):
        read_section(library, budget, 2025, "business-14")
    assert budget.spent == 0  # a refused read costs nothing


def test_budget_runs_down_across_reads(library):
    budget = ReadBudget(tokens=50_000, chars_per_token=3.0)
    first = read_section(library, budget, 2024, "business-12")
    remaining = budget.remaining
    assert remaining == 50_000 - budget.estimate(first)
    pid = first.split("]", 1)[0].lstrip("[")
    read_paragraphs(library, budget, [pid])
    assert budget.remaining < remaining


def test_unknown_items_are_refused(library):
    budget = ReadBudget(tokens=50_000, chars_per_token=3.0)
    with pytest.raises(ReadRefused, match="no section"):
        read_section(library, budget, 2025, "business-99")
    with pytest.raises(ReadRefused, match="not one of this story"):
        read_section(library, budget, 2019, "business-1")
    with pytest.raises(ReadRefused, match="unknown paragraph ids"):
        read_paragraphs(library, budget, ["MLTM-2025-p9999-001"])


def test_outline_lists_sections_without_charging(library):
    outline = library.outline(2023, "business")
    assert "13 הון חוזר  [business-13" in outline
