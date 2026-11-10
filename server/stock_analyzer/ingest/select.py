"""Pick the full annual report among a year's 10-K filings (plan.md §1.3).

Rule: fiscal year from ``fiscal_year`` or the first ``20\\d\\d`` in the title →
candidates are PDF filings without "iXBRL" in the title → the largest ``file_size`` wins.
No candidate is a loud failure naming the company and year.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from stock_analyzer.errors import ReportSelectionError
from stock_analyzer.ingest.fr_client import Filing

_YEAR = re.compile(r"20\d\d")


def filing_fiscal_year(filing: Filing) -> int | None:
    if filing.fiscal_year is not None:
        return filing.fiscal_year
    match = _YEAR.search(filing.title or "")
    return int(match.group()) if match else None


def is_candidate(filing: Filing) -> bool:
    return (filing.file_extension or "").upper() == "PDF" and "ixbrl" not in (filing.title or "").lower()


def select_report(filings: Iterable[Filing], fiscal_year: int, *, ticker: str = "?") -> Filing:
    in_year = [f for f in filings if filing_fiscal_year(f) == fiscal_year]
    candidates = [f for f in in_year if is_candidate(f)]
    if not candidates:
        seen = ", ".join(f"{f.id} ({f.file_extension or '?'}: {f.title!r})" for f in in_year) or "none"
        raise ReportSelectionError(
            f"no full annual report for {ticker} FY{fiscal_year}: no PDF filing without 'iXBRL' in the title "
            f"among that year's filings [{seen}]"
        )
    return max(candidates, key=lambda f: (f.file_size or 0, f.id))


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
