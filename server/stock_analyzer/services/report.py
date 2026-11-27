"""Company report service (company-report-spec): the radar scores, key numbers and events for one company.

Everything is computed from data already stored; nothing here calls the data provider or an LLM, and an
OSINT result is only read if one was stored (never researched).

Scoring method (anchors live in ``fin/scores.py``): each axis is a few ratios. A ratio value is mapped
linearly from its "bad" anchor (score 1) to its "good" anchor (score 10) and clamped to [1, 10]; the axis
score of a year is the mean of its available ratio scores, rounded half up to an integer. A year with no
ratio value scores ``null``. Scores are absolute (no sector median: only a few companies are tracked), the
three newest fiscal years are returned oldest first, and low-confidence ratio values are used as they are
while a ``low_confidence`` warning is raised. The trend compares an axis with the previous year (higher is
always better) and the driver names the ratio whose score moved most.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from stock_analyzer.errors import AnalyzerError, AxisNotFound, UnsupportedCompany, YearNotFound
from stock_analyzer.fin.normalize import decimal_str
from stock_analyzer.fin.ratios import RatioSeries
from stock_analyzer.fin.scores import Component, axes_for, axis_score, component_score
from stock_analyzer.ingest.select import filing_fiscal_year, select_report
from stock_analyzer.osint.models import ResearchResult
from stock_analyzer.services import filings as filings_service
from stock_analyzer.services import osint
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import (
    AxisDetailOut,
    AxisFactor,
    AxisScore,
    CompanyReportOut,
    KeyMetric,
    MetricChange,
    MetricPoint,
    ProfileAxis,
    ReportCompany,
    ReportEvent,
    ReportInfo,
    ReportProfile,
    ReportSector,
    ReportSummary,
    ReportWarning,
    ScoreDriver,
    ScoreTrend,
    Tone,
)
from stock_analyzer.services.ratios import Analysis, analyze

REPORT_YEARS = 3
EVENT_MONTHS = 36
MAX_EVENTS = 30
SECTOR_NAMES = {"industrial": "תעשייה ושירותים", "bank": "בנקאות", "insurer": "ביטוח"}
EVENT_TYPE_BY_AREA = {"credit": "financing", "labor_government": "regulatory"}
IMPORTANCE = {"high": 3, "medium": 2, "low": 1}


def trunc(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# -- scores -------------------------------------------------------------------------------------------


@dataclass
class CompYear:
    component: Component
    series: RatioSeries
    value: Decimal | None
    score: Decimal | None
    low_confidence: bool


@dataclass
class AxisYear:
    fiscal_year: int
    comps: list[CompYear]
    score: int | None


@dataclass
class AxisCalc:
    id: str
    label: str
    by_year: dict[int, AxisYear]


def report_years(a: Analysis) -> list[int]:
    """The newest three years of the analysis window, oldest first."""
    return sorted(a.years[:REPORT_YEARS])


def calc_axes(a: Analysis, years: list[int]) -> list[AxisCalc]:
    series = {s.code: s for s in a.series}
    axes: list[AxisCalc] = []
    for spec in axes_for(a.template):
        comps = [c for c in spec.components if c.code in series]
        if not comps:
            continue
        by_year: dict[int, AxisYear] = {}
        for fy in years:
            cys: list[CompYear] = []
            for c in comps:
                rv = series[c.code].values.get(fy)
                value = rv.value if rv else None
                cys.append(
                    CompYear(
                        c,
                        series[c.code],
                        value,
                        component_score(value, c.bad, c.good),
                        low_confidence=value is not None and rv is not None and rv.confidence == "low",
                    )
                )
            by_year[fy] = AxisYear(fy, cys, axis_score(cy.score for cy in cys))
        axes.append(AxisCalc(spec.id, spec.label_he, by_year))
    if sum(any(y.score is not None for y in ax.by_year.values()) for ax in axes) < 3:
        raise UnsupportedCompany(f"{a.ticker}: too little ratio data to score at least three axes")
    return axes


def trend_of(prev: int | None, cur: int | None) -> ScoreTrend | None:
    if prev is None or cur is None:
        return None
    delta = cur - prev
    if delta > 0:
        return ScoreTrend(direction="up", delta=delta, tone="positive")
    if delta < 0:
        return ScoreTrend(direction="down", delta=delta, tone="negative")
    return ScoreTrend(direction="flat", delta=0, tone="neutral")


def driver_of(prev: AxisYear, cur: AxisYear, trend: ScoreTrend | None) -> ScoreDriver | None:
    """The ratio whose score changed most since the previous year, named with the way its value moved."""
    if trend is None:
        return None
    best: tuple[Decimal, CompYear, CompYear] | None = None
    for p, c in zip(prev.comps, cur.comps, strict=True):
        if p.score is None or c.score is None or p.value is None or c.value is None:
            continue
        change = abs(c.score - p.score)
        if best is None or change > best[0]:
            best = (change, p, c)
    if best is None:
        return None
    _, p, c = best
    if trend.direction == "flat" or c.value == p.value:
        word = "יציב"
    else:
        word = "עולה" if c.value > p.value else "יורד"
    name = trunc(c.series.name_he, 28 - len(word) - 1)
    return ScoreDriver(label=f"{name} {word}", tone=trend.tone)


def profile_axis(ticker: str, ax: AxisCalc, years: list[int]) -> ProfileAxis:
    scores: list[AxisScore] = []
    for i, fy in enumerate(years):
        cur = ax.by_year[fy]
        trend = driver = None
        if i > 0:
            prev = ax.by_year[years[i - 1]]
            trend = trend_of(prev.score, cur.score)
            driver = driver_of(prev, cur, trend)
        scores.append(AxisScore(fiscal_year=fy, value=cur.score, trend=trend, driver=driver))
    has_value = any(s.value is not None for s in scores)
    return ProfileAxis(
        id=ax.id,
        label=ax.label,
        status="ok" if has_value else "insufficient_data",
        detail_url=f"/api/companies/{ticker}/report/axes/{ax.id}",
        scores=scores,
    )


def summary_text(axes: list[AxisCalc], fy: int) -> str:
    scored = [(ax.by_year[fy].score, ax.label) for ax in axes if ax.by_year[fy].score is not None]
    if not scored:
        return "אין מספיק נתונים לסיכום."
    best = max(scored, key=lambda s: s[0])  # type: ignore[arg-type, return-value]
    worst = min(scored, key=lambda s: s[0])  # type: ignore[arg-type, return-value]
    return trunc(f"החוזקה הבולטת: {best[1]} ({best[0]}). החולשה: {worst[1]} ({worst[0]}).", 160)


# -- key metrics --------------------------------------------------------------------------------------

# (id, label, up_is_good)
SHEET_METRICS = (
    ("revenue", "הכנסות", True),
    ("operating_income", "רווח תפעולי", True),
    ("net_income_parent", "רווח נקי", True),
)


def metric_change(prev: Decimal | None, cur: Decimal | None, up_is_good: bool) -> MetricChange | None:
    if prev is None or cur is None or prev == 0:
        return None
    pct = float(round((cur - prev) / abs(prev) * 100, 1))
    if cur == prev:
        return MetricChange(direction="flat", pct=0.0, tone="neutral")
    up = cur > prev
    tone: Tone = "positive" if up == up_is_good else "negative"
    return MetricChange(direction="up" if up else "down", pct=pct, tone=tone)


def make_metric(
    id_: str, label: str, values: dict[int, Decimal | None], years: list[int], currency: str, up_is_good: bool
) -> KeyMetric | None:
    if all(values.get(fy) is None for fy in years):
        return None
    cur_prev = (values.get(years[-2]) if len(years) > 1 else None, values.get(years[-1]))
    return KeyMetric(
        id=id_,
        label=label,
        format="currency",
        currency=currency,
        series=[
            MetricPoint(fiscal_year=fy, value=decimal_str(v) if (v := values.get(fy)) is not None else None)
            for fy in years
        ],
        change=metric_change(cur_prev[0], cur_prev[1], up_is_good),
    )


def key_metrics(a: Analysis, years: list[int], currency: str) -> list[KeyMetric]:
    sheet = a.sheet
    candidates: list[tuple[str, str, dict[int, Decimal | None], bool]] = []
    for field, label, good in SHEET_METRICS:
        candidates.append((field, label, {fy: sheet.value(fy, field) for fy in years}, good))
    fcf = next((s for s in a.series if s.code == "free_cash_flow"), None)
    if fcf is not None:
        candidates.append(
            (
                "free_cash_flow",
                "תזרים מזומנים חופשי",
                {fy: fcf.values[fy].value if fy in fcf.values else None for fy in years},
                True,
            )
        )
    net_debt: dict[int, Decimal | None] = {}
    for fy in years:
        debt = sheet.value(fy, "total_debt")
        cash = sheet.value(fy, "cash_and_st_investments")
        if cash is None:
            cash = sheet.value(fy, "cash")
        net_debt[fy] = debt - cash if debt is not None and cash is not None else None
    candidates.append(("net_debt", "חוב נטו", net_debt, False))
    candidates.append(
        ("total_equity", "הון עצמי", {fy: sheet.value(fy, "total_equity") for fy in years}, True)
    )
    metrics = [make_metric(i, lb, vals, years, currency, good) for i, lb, vals, good in candidates]
    return [m for m in metrics if m is not None][:8]


# -- events -------------------------------------------------------------------------------------------

DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def parse_published(text: str | None) -> tuple[str, str, date] | None:
    """(date text, precision, sortable date) from ``YYYY-MM-DD`` or ``YYYY-MM``; None when unusable."""
    if not text:
        return None
    try:
        if m := DAY.match(text):
            d = date(int(m[1]), int(m[2]), int(m[3]))
            return d.isoformat(), "day", d
        if m := MONTH.match(text):
            d = date(int(m[1]), int(m[2]), 1)
            return f"{m[1]}-{m[2]}", "month", d
    except ValueError:
        return None
    return None


def events_from(result: ResearchResult, today: date) -> list[ReportEvent]:
    start = osint.window_start(today, EVENT_MONTHS)
    dated: list[tuple[date, ReportEvent]] = []
    for f in result.findings:
        parsed = parse_published(f.published_at)
        if parsed is None or not (start <= parsed[2] <= today):
            continue
        text, precision, d = parsed
        dated.append(
            (
                d,
                ReportEvent(
                    id=f"ev-{f.id}",
                    date=text,
                    date_precision=precision,  # type: ignore[arg-type]
                    type=EVENT_TYPE_BY_AREA.get(f.area, "other"),  # type: ignore[arg-type]
                    title=trunc(f.source_title or f.claim, 40),
                    summary=trunc(f.claim, 80),
                    importance=IMPORTANCE[f.confidence],
                    tone=f.signal,
                    source_url=f.source_url or None,
                ),
            )
        )
    dated.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in dated[:MAX_EVENTS]]


def stored_events(ctx: Ctx, ticker: str, today: date) -> list[ReportEvent]:
    try:
        return events_from(osint.stored_result(ctx, ticker), today)
    except AnalyzerError:  # no stored OSINT result (or none readable): the report has no events
        return []


# -- the report ---------------------------------------------------------------------------------------


def published_at(ctx: Ctx, ticker: str, fy: int) -> str | None:
    try:
        in_year = [f for f in filings_service.company_filings(ctx, ticker) if filing_fiscal_year(f) == fy]
        selected = select_report(in_year, fy, ticker=ticker)
    except Exception:  # noqa: BLE001 - the date is a nicety; the period end stands in
        return None
    return selected.release_datetime.date().isoformat() if selected.release_datetime else None


def build_warnings(axes: list[AxisCalc], years: list[int], fy: int, today: date) -> list[ReportWarning]:
    warnings: list[ReportWarning] = []
    if fy < today.year - 1:
        warnings.append(
            ReportWarning(code="stale_report", message=f"הדוח השנתי האחרון הוא של {fy}, ייתכן שהוא מיושן.")
        )
    low = list(
        dict.fromkeys(
            cy.series.name_he
            for ax in axes
            for fy_ in years
            for cy in ax.by_year[fy_].comps
            if cy.low_confidence
        )
    )
    if low:
        shown = ", ".join(low[:3]) + ("…" if len(low) > 3 else "")
        warnings.append(
            ReportWarning(
                code="low_confidence",
                message=f"חלק מהציונים מבוססים על נתונים בביטחון נמוך ({shown}).",
            )
        )
    return warnings


def company_report(ctx: Ctx, ticker: str, *, today: date | None = None) -> CompanyReportOut:
    today = today or date.today()
    a = analyze(ctx, ticker)
    company = resolve_company(ctx, ticker)
    years = report_years(a)
    axes = calc_axes(a, years)
    fy = years[-1]
    currency = a.currency or "ILS"
    period_end = f"{fy}-12-31"
    return CompanyReportOut(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        mode=ctx.mode,
        company=ReportCompany(
            ticker=company.ticker,
            name_he=company.name_he,
            name_en=company.name_en,
            exchange="TASE",
            currency=currency,
            sector=ReportSector(id=a.template, name=SECTOR_NAMES.get(a.template, a.template)),
        ),
        report=ReportInfo(
            fiscal_year=fy,
            period_end=period_end,
            published_at=published_at(ctx, company.ticker, fy) or period_end,
        ),
        summary=ReportSummary(text=summary_text(axes, fy)),
        years=years,
        profile=ReportProfile(axes=[profile_axis(company.ticker, ax, years) for ax in axes]),
        events=stored_events(ctx, company.ticker, today),
        key_metrics=key_metrics(a, years, currency),
        warnings=build_warnings(axes, years, fy, today),
    )


# -- axis detail --------------------------------------------------------------------------------------


def compact(value: Decimal) -> str:
    n = abs(value)
    for limit, suffix in ((Decimal(10) ** 9, "B"), (Decimal(10) ** 6, "M"), (Decimal(10) ** 3, "K")):
        if n >= limit:
            return f"{value / limit:.1f}{suffix}"
    return f"{value:.0f}"


def display_value(series: RatioSeries, value: Decimal | None) -> str:
    if value is None:
        return "—"
    if series.unit == "percent":
        return f"{value * 100:.1f}%"
    if series.unit == "amount":
        return compact(value)
    if series.unit == "days":
        return f"{value:.0f}"
    return f"{value:.1f}x"


def display_anchor(series: RatioSeries, x: Decimal) -> str:
    if series.unit == "percent":
        return format((x * 100).normalize(), "f") + "%"
    return f"{x:.1f}"


def factor_tone(score: Decimal | None) -> Tone:
    if score is None:
        return "neutral"
    return "positive" if score >= 7 else "negative" if score <= 4 else "neutral"


def axis_text(comps: list[CompYear]) -> str:
    parts = [
        f"{cy.series.name_he} ({display_anchor(cy.series, cy.component.bad)}=1, "
        f"{display_anchor(cy.series, cy.component.good)}=10)"
        for cy in comps
    ]
    if len(parts) == 1:
        return trunc(f"הציון נקבע לפי: {parts[0]}.", 600)
    return trunc(f"הציון הוא ממוצע של: {', '.join(parts[:-1])} ו-{parts[-1]}.", 600)


def axis_detail(ctx: Ctx, ticker: str, axis_id: str, year: int | None = None) -> AxisDetailOut:
    a = analyze(ctx, ticker)
    years = report_years(a)
    axes = calc_axes(a, years)
    ax = next((x for x in axes if x.id == axis_id), None)
    if ax is None:
        raise AxisNotFound(f"{a.ticker}: no axis {axis_id!r}; available: {', '.join(x.id for x in axes)}")
    fy = year if year is not None else years[-1]
    if fy not in years:
        raise YearNotFound(f"{a.ticker}: no scores for {fy}; available years: {', '.join(map(str, years))}")
    ay = ax.by_year[fy]
    headline = f"{ax.label}: {ay.score} מתוך 10" if ay.score is not None else f"{ax.label}: אין מספיק נתונים"
    return AxisDetailOut(
        axis_id=ax.id,
        fiscal_year=fy,
        headline=trunc(headline, 80),
        factors=[
            AxisFactor(
                label=cy.series.name_he,
                display=display_value(cy.series, cy.value),
                tone=factor_tone(cy.score),
            )
            for cy in ay.comps[:5]
        ],
        sector_comparison=None,
        text=axis_text(ay.comps),
    )
