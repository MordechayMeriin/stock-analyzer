"""Building the company report from a story run and a verified rating (company-report spec, design D4).

Nothing here calls an LLM or the provider. Every displayed number comes from the run's facts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from stock_analyzer.companies import TrackedCompany
from stock_analyzer.report.models import (
    AXES,
    SCHEMA_VERSION,
    Axis,
    AxisDetail,
    Company,
    CompanyReport,
    Driver,
    Factor,
    KeyMetric,
    MetricChange,
    MetricPoint,
    Profile,
    RaterOutput,
    ReportEvent,
    ReportInfo,
    Score,
    Sector,
    Summary,
    Trend,
)
from stock_analyzer.story.facts import FactRegistry
from stock_analyzer.story.pipeline import StoryRun
from stock_analyzer.story.render import format_fact

UNKNOWN_SECTOR = Sector(id="unknown", name="לא ידוע")

# (metric id, fact kind, format): the key metrics every report shows (company-report spec).
KEY_METRICS: tuple[tuple[str, str, Literal["currency", "percent"]], ...] = (
    ("revenue", "FIN", "currency"),
    ("operating_margin", "RATIO", "percent"),
    ("net_income_consolidated", "FIN", "currency"),
    ("cfo", "FIN", "currency"),
)


def trend_of(previous: int | None, current: int | None) -> Trend | None:
    if previous is None or current is None:
        return None
    delta = current - previous
    if delta > 0:
        return Trend(direction="up", delta=delta, tone="positive")
    if delta < 0:
        return Trend(direction="down", delta=delta, tone="negative")
    return Trend(direction="flat", delta=0, tone="neutral")


def _axes(run: StoryRun, rating: RaterOutput) -> list[Axis]:
    rated = {a.axis_id: {y.fiscal_year: y for y in a.years} for a in rating.axes}
    axes: list[Axis] = []
    for axis_id, label in AXES:
        years = rated.get(axis_id, {})
        scores: list[Score] = []
        previous: int | None = None
        for i, fy in enumerate(run.years):
            y = years.get(fy)
            value = y.value if y is not None else None
            trend = trend_of(previous, value) if i > 0 else None
            driver = (
                Driver(label=y.driver_label, tone=y.driver_tone or "neutral")
                if trend is not None and y is not None and y.driver_label
                else None
            )
            scores.append(Score(fiscal_year=fy, value=value, sector_median=None, trend=trend, driver=driver))
            previous = value
        status = "insufficient_data" if any(s.value is None for s in scores) else "ok"
        axes.append(
            Axis(
                id=axis_id,
                label=label,
                status=status,
                detail_url=f"/api/companies/{run.ticker}/report/axes/{axis_id}",
                scores=scores,
            )
        )
    return axes


def details_of(run: StoryRun, rating: RaterOutput) -> list[AxisDetail]:
    registry = FactRegistry(run.facts)
    details: list[AxisDetail] = []
    for axis in rating.axes:
        for y in axis.years:
            if y.value is None:
                continue
            details.append(
                AxisDetail(
                    axis_id=axis.axis_id,
                    fiscal_year=y.fiscal_year,
                    headline=y.headline or "",
                    factors=[
                        Factor(label=f.label, display=format_fact(registry.get(f.fact_id)), tone=f.tone)
                        for f in y.factors
                    ],
                    sector_comparison=None,
                    text=y.text or "",
                )
            )
    return details


def _events(rating: RaterOutput) -> list[ReportEvent]:
    events = [
        ReportEvent(
            id=f"ev-{e.date.replace('-', '')}-{e.type}-{i + 1}",
            date=e.date,
            date_precision=e.date_precision,
            type=e.type,
            title=e.title,
            summary=e.summary,
            importance=e.importance,
            tone=e.tone,
            source_url=None,
        )
        for i, e in enumerate(rating.events)
    ]
    return sorted(events, key=lambda e: e.date, reverse=True)


def _change(prev: str | None, cur: str | None) -> MetricChange | None:
    if prev is None or cur is None:
        return None
    p, c = Decimal(prev), Decimal(cur)
    if p == 0:
        return None
    pct = float(round((c - p) / abs(p) * 100, 1))
    if pct > 0:
        return MetricChange(direction="up", pct=pct, tone="positive")
    if pct < 0:
        return MetricChange(direction="down", pct=pct, tone="negative")
    return MetricChange(direction="flat", pct=0.0, tone="neutral")


def _key_metrics(run: StoryRun, currency: str) -> list[KeyMetric]:
    registry = FactRegistry(run.facts)
    metrics: list[KeyMetric] = []
    for code, kind, fmt in KEY_METRICS:
        ids = [f"{kind}:{code}:{fy}" for fy in run.years]
        facts = [registry.get(i) if i in registry else None for i in ids]
        named = next((f for f in facts if f is not None), None)
        if named is None:
            continue
        series = [
            MetricPoint(fiscal_year=fy, value=f.value if f else None)
            for fy, f in zip(run.years, facts, strict=True)
        ]
        change = _change(series[-2].value, series[-1].value) if len(series) > 1 else None
        metrics.append(
            KeyMetric(
                id=code,
                label=named.name_he,
                format=fmt,
                currency=currency if fmt == "currency" else None,
                series=series,
                change=change,
            )
        )
    return metrics


def currency_of(run: StoryRun) -> str:
    return next((f.currency for f in run.facts if f.kind == "FIN" and f.currency), "ILS")


def assemble(
    run: StoryRun,
    rating: RaterOutput,
    company: TrackedCompany,
    *,
    mode: Literal["cached", "live"],
    sector: Sector | None = None,
    published_at: str | None = None,
    now: datetime | None = None,
) -> CompanyReport:
    fy = max(run.years)
    currency = currency_of(run)
    return CompanyReport(
        schema_version=SCHEMA_VERSION,
        generated_at=(now or datetime.now(UTC)).isoformat(timespec="seconds"),
        mode=mode,
        company=Company(
            ticker=run.ticker,
            name_he=company.name_he,
            name_en=company.name_en,
            logo_url=None,
            exchange="TASE",
            currency=currency,
            sector=sector or UNKNOWN_SECTOR,
        ),
        report=ReportInfo(fiscal_year=fy, period_end=f"{fy}-12-31", published_at=published_at or run.as_of),
        summary=Summary(text=rating.summary),
        years=list(run.years),
        profile=Profile(axes=_axes(run, rating)),
        events=_events(rating),
        key_metrics=_key_metrics(run, currency),
        warnings=[],
    )
