"""Which reports a story covers: the three latest annual reports published by ``as_of``."""

from __future__ import annotations

from datetime import date

from stock_analyzer.errors import ReportSelectionError, StoryReportsMissing
from stock_analyzer.ingest.fr_client import Filing
from stock_analyzer.ingest.select import filing_fiscal_year, select_report

STORY_YEARS = 3


def story_reports(filings: list[Filing], as_of: date, *, ticker: str) -> list[tuple[int, Filing]]:
    """(fiscal year, selected filing) for the three latest years published on or before ``as_of``,
    oldest first. Fewer than three raises an error naming the missing fiscal years."""
    years = sorted({y for f in filings if (y := filing_fiscal_year(f)) is not None}, reverse=True)
    available: list[tuple[int, Filing]] = []
    for year in years:
        try:
            filing = select_report([f for f in filings if filing_fiscal_year(f) == year], year, ticker=ticker)
        except ReportSelectionError:
            continue
        published = filing.release_datetime.date() if filing.release_datetime else None
        if published is not None and published <= as_of:
            available.append((year, filing))
    chosen = sorted(available[:STORY_YEARS])
    if len(chosen) < STORY_YEARS:
        latest = chosen[-1][0] if chosen else as_of.year - 1
        expected = range(latest - STORY_YEARS + 1, latest + 1)
        have = {y for y, _ in chosen}
        missing = ", ".join(f"FY{y}" for y in expected if y not in have)
        raise StoryReportsMissing(
            f"a story needs the last {STORY_YEARS} annual reports published by {as_of.isoformat()}; "
            f"missing: {missing or 'earlier years'}"
        )
    return chosen
