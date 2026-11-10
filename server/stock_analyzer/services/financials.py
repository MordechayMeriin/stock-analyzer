"""Financials service: normalized values grouped by statement and fiscal year (≤ 5 years)."""

from __future__ import annotations

from datetime import date

from stock_analyzer.companies import resolve_ticker
from stock_analyzer.fin.normalize import (
    STATEMENT_LABELS_HE,
    STATEMENT_ORDER,
    FinValue,
    check_currency,
    decimal_str,
    normalize_financials,
)
from stock_analyzer.fin.normalize import (
    as_of as filter_as_of,
)
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import FinancialsOut, FinItemOut, FinStatementOut


def fin_values(ctx: Ctx, ticker: str, *, as_of: date | None = None) -> list[FinValue]:
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    values = normalize_financials(ctx.fr.get_financials(company.fr_company_id))
    return filter_as_of(values, as_of) if as_of else values


def financials(
    ctx: Ctx, ticker: str, *, as_of: date | None = None, max_years: int | None = None
) -> FinancialsOut:
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    values = fin_values(ctx, company.ticker, as_of=as_of)
    currency = check_currency(values)
    limit = max_years or ctx.settings.fin_max_years
    years = sorted({v.fiscal_year for v in values}, reverse=True)[:limit]
    statements: list[FinStatementOut] = []
    for statement in STATEMENT_ORDER:
        rows: dict[str, list[FinValue]] = {}
        for v in values:
            if v.statement == statement and v.fiscal_year in years:
                rows.setdefault(v.code, []).append(v)
        if not rows:
            continue
        items = []
        for code, vs in sorted(rows.items(), key=lambda kv: (min(v.sort_order for v in kv[1]), kv[0])):
            by_year = {v.fiscal_year: v for v in vs}
            items.append(
                FinItemOut(
                    code=code,
                    label=vs[0].label,
                    depth=vs[0].depth,
                    values={str(y): (decimal_str(by_year[y].value) if y in by_year else None) for y in years},
                    as_reported={str(y): by_year[y].as_reported for y in years if y in by_year},
                )
            )
        statements.append(
            FinStatementOut(statement=statement, label=STATEMENT_LABELS_HE[statement], items=items)
        )
    available: dict[str, str | None] = {}
    for y in years:
        stamps = [v.available_at for v in values if v.fiscal_year == y and v.available_at]
        available[str(y)] = min(stamps).isoformat() if stamps else None
    return FinancialsOut(
        ticker=company.ticker,
        currency=currency,
        years=years,
        as_of=as_of.isoformat() if as_of else None,
        statements=statements,
        available_at=available,
    )
