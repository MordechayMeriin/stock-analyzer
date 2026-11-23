"""Reference reports (report-parsing spec: Reference reports).

Every parser change is checked against six full reports from four issuers. Section and note
coverage is relative to what each report contains: El Al has only 8-9 top-level business sections,
and Delek's provider text has a note heading for only some of its notes. The reports are read
through the state store (``DATA_DIR``, or the ``DATABASE_URL`` store); absent ones are skipped.
"""

from __future__ import annotations

import logging
import re

import pytest

from stock_analyzer.ingest.normalize import normalize_title
from stock_analyzer.ingest.parse_md import parse_report
from stock_analyzer.ingest.structure import MAIN_CHAPTERS, Structure, build_structure
from tests.conftest import REFERENCE_REPORTS, live_report

# a line that opens with the note word and a number: "ביאור 3 - …", "באור 2: …"
NOTE_HEADING_LINE = re.compile(r"^(?:ביאור|באור)\s+(\d{1,2})\s*[-–:]")


def _structure(ticker: str, fiscal_year: int):
    text, filing_id = live_report(ticker, fiscal_year)
    logging.disable(logging.WARNING)
    try:
        parsed = parse_report(text, ticker=ticker, fiscal_year=fiscal_year, filing_id=filing_id)
        return parsed, build_structure(parsed)
    finally:
        logging.disable(logging.NOTSET)


def note_numbers_with_a_heading(parsed, structure: Structure) -> set[int]:
    """Note numbers of the main statement set whose heading line appears in the text, counted from
    the raw paragraphs (independently of how the structure recognised them)."""
    fin = structure.node("financials")
    first, last = fin.para_range
    groups = [
        n.para_range[0]
        for n in structure.nodes
        if n.chapter == "financials" and n.kind == "other" and n.node_id != "financials-notes"
    ]
    last = min([last] + [g - 1 for g in groups if g > first])
    return {
        int(m.group(1))
        for p in parsed.paragraphs[first : last + 1]
        if not p.in_table
        for line in p.raw.split("\n")
        if (m := NOTE_HEADING_LINE.match(normalize_title(line)))
    }


@pytest.mark.live_data
@pytest.mark.parametrize(
    ("ticker", "fiscal_year"), REFERENCE_REPORTS, ids=[f"{t}-{y}" for t, y in REFERENCE_REPORTS]
)
def test_reference_report(ticker, fiscal_year):
    parsed, s = _structure(ticker, fiscal_year)
    c = s.coverage

    # each main chapter exactly once
    assert c.chapters_found == list(MAIN_CHAPTERS), c.chapters_found
    assert c.chapters_missing == [] and c.chapters_duplicated == []

    # business sections: at least 80% of the report's own top-level TOC entries
    if c.business_sections_source == "toc":
        assert c.business_toc_entries > 0
        assert c.business_sections_matched_from_toc >= 0.8 * c.business_toc_entries, (
            f"{c.business_sections_matched_from_toc}/{c.business_toc_entries} TOC entries matched"
        )
    else:
        assert c.business_sections >= 10

    # notes: at least 90% of the main set's note numbers that have a heading line in the text
    expected = note_numbers_with_a_heading(parsed, s)
    found = {int(n.number) for n in s.nodes if n.node_id.startswith("financials-note-")}
    assert expected, "no note heading lines found in the main statement set"
    assert len(expected & found) >= 0.9 * len(expected), f"missing notes {sorted(expected - found)}"

    # the primary statements
    assert c.statements >= 4
