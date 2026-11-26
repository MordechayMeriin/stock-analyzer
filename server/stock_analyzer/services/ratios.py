"""Ratios service: cached financials → canonical sheet → checks → ratio series (financial-ratios spec).

One function feeds the CLI ``ratios`` command, ``GET /api/companies/{ticker}/ratios`` and the LLM tools
(``tools.py``), so all three return the same numbers. Ratios are recomputed on every call from cached
financials (no provider call in cached mode, nothing persisted).

Ratios are computed over every fiscal year in the sheet (averages and growth need the year before), then
the output keeps the newest ``fin_max_years`` contiguous calendar years ending at the latest one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from stock_analyzer.errors import TemplateNotSupported
from stock_analyzer.fin.canonical import Sheet, build_sheet
from stock_analyzer.fin.checks import CheckResult, run_checks
from stock_analyzer.fin.normalize import check_currency, decimal_str
from stock_analyzer.fin.ratios import GROUP_LABELS_HE, RatioSeries, RatioValue, compute
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.financials import company_financials
from stock_analyzer.services.models import (
    CheckOut,
    RatioGroupOut,
    RatioSeriesOut,
    RatiosOut,
    RatioValueOut,
)

RATIO_QUANTUM = Decimal("0.000001")


@dataclass
class Analysis:
    ticker: str
    template: str
    currency: str | None
    as_of: date | None
    years: list[int]  # output window, newest first
    sheet: Sheet
    checks: dict[int, list[CheckResult]]
    series: list[RatioSeries]


def window(sheet_years: list[int], max_years: int) -> list[int]:
    """The newest ``max_years`` contiguous calendar years ending at the latest year that has data."""
    if not sheet_years:
        return []
    latest = max(sheet_years)
    return [y for y in range(latest, latest - max_years, -1) if y in sheet_years]


def analyze(ctx: Ctx, ticker: str, *, as_of: date | None = None, max_years: int | None = None) -> Analysis:
    company = resolve_company(ctx, ticker)
    fin = company_financials(ctx, company.ticker, as_of=as_of)
    try:
        sheet = build_sheet(fin.values, fin.template)
    except TemplateNotSupported as exc:
        raise TemplateNotSupported(f"{company.ticker}: {exc.message}") from None
    checks = run_checks(sheet)
    return Analysis(
        ticker=company.ticker,
        template=sheet.template,
        currency=check_currency(fin.values),
        as_of=as_of,
        years=window(sheet.years, max_years or ctx.settings.fin_max_years),
        sheet=sheet,
        checks=checks,
        series=compute(sheet, checks),
    )


def dec(value: Decimal | None, quantum: Decimal | None = None) -> str | None:
    if value is None:
        return None
    return decimal_str(value.quantize(quantum) if quantum is not None else value)


def value_out(v: RatioValue) -> RatioValueOut:
    return RatioValueOut(
        value=dec(v.value, RATIO_QUANTUM),
        missing_reason=v.missing_reason,
        missing_message_he=v.missing_message_he,
        confidence=v.confidence,
        failed_checks=v.failed_checks,
        derived_inputs=v.derived_inputs,
        avg_used=v.avg_used,
        inputs={k: decimal_str(x) for k, x in v.inputs.items()},
        delta=dec(v.delta, RATIO_QUANTUM),
        status=v.status,
        notes=v.notes,
    )


def series_out(s: RatioSeries, years: list[int]) -> RatioSeriesOut:
    return RatioSeriesOut(
        code=s.code,
        name_he=s.name_he,
        unit=s.unit,
        direction=s.direction,
        threshold=decimal_str(s.threshold),
        values={str(fy): value_out(s.values[fy]) for fy in years},
    )


def check_out(r: CheckResult) -> CheckOut:
    return CheckOut(
        id=r.id,
        label_he=r.label_he,
        status=r.status,
        cells=r.cells,
        left=dec(r.left),
        right=dec(r.right),
        difference=dec(r.difference),
        reason=r.reason,
    )


def ratios_out(a: Analysis) -> RatiosOut:
    groups: dict[str, list[RatioSeriesOut]] = {}
    for s in a.series:
        groups.setdefault(s.group, []).append(series_out(s, a.years))
    return RatiosOut(
        ticker=a.ticker,
        template=a.template,
        currency=a.currency,
        years=a.years,
        as_of=a.as_of.isoformat() if a.as_of else None,
        groups=[RatioGroupOut(group=g, label=GROUP_LABELS_HE[g], ratios=rs) for g, rs in groups.items()],
        checks={str(fy): [check_out(r) for r in a.checks[fy]] for fy in a.years},
    )


def ratios(ctx: Ctx, ticker: str, *, as_of: date | None = None, max_years: int | None = None) -> RatiosOut:
    return ratios_out(analyze(ctx, ticker, as_of=as_of, max_years=max_years))
