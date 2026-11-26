"""Pick the full annual report among a year's 10-K filings (plan.md §1.3).

Rule: fiscal year from ``fiscal_year`` or the first ``20\\d\\d`` in the title →
candidates are PDF filings without "iXBRL" in the title whose title names a periodic report
(``תקופתי``, or ``periodic`` in any case; a bond-trustee "annual report" is not one) → a candidate
whose Markdown is available or of unknown status beats one the provider has not processed or could
not convert (:func:`markdown_availability`) → within the same availability the largest ``file_size``
wins. A year whose candidates are all unprocessed still selects one, so callers can say which filing
it waits for. PDF only describes the provider filing whose Markdown is fetched; nothing links to it.
No candidate is a loud failure naming the company and year.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from stock_analyzer.errors import ReportSelectionError
from stock_analyzer.ingest.fr_client import Filing

_YEAR = re.compile(r"20\d\d")
_PERIODIC = re.compile(r"תקופתי|periodic", re.IGNORECASE)

Availability = Literal["available", "unknown", "processing", "failed"]

# The provider's processing_status → whether the filing's Markdown can be fetched. A missing or
# unrecognised status means unknown: the provider treats it as "try it", not as "not ready".
_AVAILABILITY_BY_STATUS: dict[str, Availability] = {
    "COMPLETED": "available",
    "PENDING": "processing",
    "QUEUED": "processing",
    "PROCESSING": "processing",
    "FAILED": "failed",
    "SKIPPED": "failed",
}
_RANK: dict[Availability, int] = {"available": 2, "unknown": 2, "processing": 1, "failed": 0}


def markdown_availability(filing: Filing) -> Availability:
    status = (filing.processing_status or "").strip().upper()
    return _AVAILABILITY_BY_STATUS.get(status, "unknown")


def is_ready(filing: Filing) -> bool:
    """False when the provider says it has no Markdown for the filing (yet)."""
    return markdown_availability(filing) in ("available", "unknown")


def filing_fiscal_year(filing: Filing) -> int | None:
    if filing.fiscal_year is not None:
        return filing.fiscal_year
    match = _YEAR.search(filing.title or "")
    return int(match.group()) if match else None


def is_candidate(filing: Filing) -> bool:
    title = filing.title or ""
    return (
        (filing.file_extension or "").upper() == "PDF"
        and "ixbrl" not in title.lower()
        and bool(_PERIODIC.search(title))
    )


def select_report(filings: Iterable[Filing], fiscal_year: int, *, ticker: str = "?") -> Filing:
    in_year = [f for f in filings if filing_fiscal_year(f) == fiscal_year]
    candidates = [f for f in in_year if is_candidate(f)]
    if not candidates:
        seen = ", ".join(f"{f.id} ({f.file_extension or '?'}: {f.title!r})" for f in in_year) or "none"
        raise ReportSelectionError(
            f"no full annual report for {ticker} FY{fiscal_year}: no PDF filing titled as a periodic report "
            f"(תקופתי / periodic) without 'iXBRL' among that year's filings [{seen}]"
        )
    return max(candidates, key=lambda f: (_RANK[markdown_availability(f)], f.file_size or 0, f.id))


def selected_by_year(filings: Iterable[Filing], *, ticker: str = "?") -> dict[int, Filing]:
    """The selected report for every fiscal year that has a candidate."""
    filings = list(filings)
    years = sorted({y for f in filings if (y := filing_fiscal_year(f)) is not None}, reverse=True)
    result: dict[int, Filing] = {}
    for year in years:
        try:
            result[year] = select_report(filings, year, ticker=ticker)
        except ReportSelectionError:
            continue
    return result
