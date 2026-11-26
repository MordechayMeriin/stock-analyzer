"""Report comparison service: business sections aligned across fiscal years (report-diff spec).

The CLI ``compare`` command and ``GET /api/companies/{ticker}/compare`` both call :func:`compare`.
"""

from __future__ import annotations

from collections.abc import Sequence

from stock_analyzer.companies import resolve_ticker
from stock_analyzer.diff.align import Comparison, Report, compare_business
from stock_analyzer.services import reports
from stock_analyzer.services.context import Ctx


def load_reports(ctx: Ctx, ticker: str, years: Sequence[int]) -> list[Report]:
    out = []
    for fy in sorted(set(years)):
        parsed, structure, _meta = reports.load_parsed(ctx, ticker, fy)
        out.append(Report(fy, parsed, structure))
    return out


def compare(ctx: Ctx, ticker: str, years: Sequence[int]) -> Comparison:
    if len(set(years)) < 2:
        raise ValueError("comparing reports needs at least two different fiscal years")
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    s = ctx.settings
    return compare_business(
        company.ticker,
        load_reports(ctx, company.ticker, years),
        unchanged_threshold=s.diff_unchanged_threshold,
        title_threshold=s.diff_title_match_threshold,
        content_threshold=s.diff_content_match_threshold,
    )
