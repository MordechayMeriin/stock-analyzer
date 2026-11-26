"""Financial analysis service: core ratios, changes and data-quality checks (financial-analysis spec).

The CLI ``ratios`` command and ``GET /api/companies/{ticker}/ratios`` both call :func:`ratios`.
"""

from __future__ import annotations

from datetime import date

from stock_analyzer.companies import resolve_ticker
from stock_analyzer.fin.checks import run_checks
from stock_analyzer.fin.normalize import FinValue, check_currency
from stock_analyzer.fin.ratios import compute_changes, compute_ratios
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.financials import fin_values
from stock_analyzer.services.models import RatiosOut


def recent_values(ctx: Ctx, ticker: str, *, as_of: date | None, max_years: int | None) -> list[FinValue]:
    """Normalized values for the most recent fiscal years available at ``as_of``."""
    values = fin_values(ctx, ticker, as_of=as_of)
    limit = max_years or ctx.settings.fin_max_years
    years = set(sorted({v.fiscal_year for v in values}, reverse=True)[:limit])
    return [v for v in values if v.fiscal_year in years]


def ratios(ctx: Ctx, ticker: str, *, as_of: date | None = None, max_years: int | None = None) -> RatiosOut:
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    values = recent_values(ctx, company.ticker, as_of=as_of, max_years=max_years)
    currency = check_currency(values)
    checks = run_checks(values, ctx.settings.check_tolerances)
    ratio_values = compute_ratios(values, checks)
    changes = [c for c in compute_changes(values, ratio_values, checks) if c.kind == "RATIO"]
    return RatiosOut(
        ticker=company.ticker,
        currency=currency,
        years=sorted({v.fiscal_year for v in values}, reverse=True),
        as_of=as_of.isoformat() if as_of else None,
        ratios=ratio_values,
        changes=changes,
        checks=checks,
    )
