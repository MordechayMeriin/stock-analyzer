"""Story-based company report: the five axes scored from the latest story run (company-report spec).

``services.report`` serves this report first and falls back to its ratio scoring when there is none
to serve. A report is saved in the store's ``report`` cache, keyed by ticker and story run id, so it
is built once per story run.
"""

from __future__ import annotations

import asyncio
import logging

from stock_analyzer.agents_model import run_agent
from stock_analyzer.errors import AxisNotFound, NotCached, ReportVerificationFailed, YearNotFound
from stock_analyzer.ingest.fr_client import FRClient
from stock_analyzer.report.assemble import assemble, details_of
from stock_analyzer.report.models import AxisDetail, CompanyReport, RaterOutput, SavedReport, Sector
from stock_analyzer.report.rater import prompt_hash, rater_agent, rater_input, repair_input
from stock_analyzer.report.verify import verify_rating
from stock_analyzer.services import story as story_service
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import AxisDetailOut, CompanyReportOut
from stock_analyzer.story.agents import ModelFactory
from stock_analyzer.story.facts import FactRegistry
from stock_analyzer.story.pipeline import StoryRun

log = logging.getLogger(__name__)
RATER_MAX_TURNS = 2


def cache_key(ticker: str, run_id: str) -> str:
    return f"{ticker.upper()}:{run_id}"


def _sector(ctx: Ctx, fr_company_id: int) -> Sector | None:
    """The provider's sub-industry, from the cache only: building a report never spends credits."""
    try:
        client = FRClient(ctx.settings, mode="cached", store=ctx.store)
        try:
            sub = client.company_profile(fr_company_id).sub_industry
        finally:
            client.close()
    except NotCached:
        return None
    except Exception:  # noqa: BLE001 - the sector is decoration; never fail a report over it
        log.warning("sector lookup failed for company %s", fr_company_id, exc_info=True)
        return None
    if sub is None or not (sub.code or sub.name):
        return None
    return Sector(id=(sub.code or "unknown").strip(), name=(sub.name or sub.code or "").strip())


def _published_at(ctx: Ctx, run: StoryRun) -> str | None:
    loaded = ctx.store.load_report(run.ticker, max(run.years))
    if loaded is None or loaded[1].release_datetime is None:
        return None
    return loaded[1].release_datetime.date().isoformat()


async def rate(ctx: Ctx, run: StoryRun, models: ModelFactory) -> RaterOutput:
    """The rater's verified output: one repair turn on verification errors, then fail."""
    registry = FactRegistry(run.facts)
    base = rater_input(run)
    agent_input = base
    errors: list[str] = []
    for _attempt in (1, 2):
        out = await run_agent(rater_agent(ctx.settings, models), agent_input, max_turns=RATER_MAX_TURNS)
        errors = verify_rating(out, registry, run.years)
        if not errors:
            return out
        agent_input = repair_input(base, out, errors)
    raise ReportVerificationFailed(
        f"the report scores failed verification after one repair ({len(errors)} errors)", errors
    )


def _saved(ctx: Ctx, run: StoryRun) -> SavedReport | None:
    data = ctx.store.cache("report").get(cache_key(run.ticker, run.run_id))
    return SavedReport.model_validate(data) if data is not None else None


def build(ctx: Ctx, ticker: str, *, models: ModelFactory | None = None) -> tuple[SavedReport, bool]:
    """The saved report for the latest story run, and whether it was built by this call.

    Cached mode only reads it. Live mode builds and saves it when it is missing.
    """
    company = resolve_company(ctx, ticker)
    run = story_service.latest(ctx, company.ticker)
    saved = _saved(ctx, run)
    if saved is not None:
        return saved, False
    if ctx.mode != "live":
        raise NotCached(
            f"no report built yet for {company.ticker}'s latest story; request it in live mode "
            f"(stock-analyzer report {company.ticker} --live)"
        )
    factory = story_service.resolve_models(ctx, models)
    rating = asyncio.run(rate(ctx, run, factory))
    report = assemble(
        run,
        rating,
        company,
        mode="live",
        sector=_sector(ctx, company.fr_company_id),
        published_at=_published_at(ctx, run),
    )
    saved = SavedReport(
        run_id=run.run_id,
        prompt_hash=prompt_hash(ctx.settings),
        report=report,
        details=details_of(run, rating),
    )
    ctx.store.cache("report").set(cache_key(run.ticker, run.run_id), saved.model_dump(mode="json"))
    return saved, True


def get_report(ctx: Ctx, ticker: str, *, models: ModelFactory | None = None) -> CompanyReport:
    """The report, with ``mode`` saying how this response was served: built now, or read from the store."""
    saved, fresh = build(ctx, ticker, models=models)
    return saved.report.model_copy(update={"mode": "live" if fresh else "cached"})


def get_axis_detail(ctx: Ctx, ticker: str, axis_id: str, year: int) -> AxisDetail:
    """One axis's detail for a year, from the saved report (never builds one)."""
    saved, _ = build(ctx.__class__(settings=ctx.settings, mode="cached", _store=ctx.store), ticker)
    for d in saved.details:
        if d.axis_id == axis_id and d.fiscal_year == year:
            return d
    raise AxisNotFound(f"no {axis_id!r} score for {year} in {ticker.upper()}'s report")


# ---------------------------------------------------------------- serving through services.report


def _to_out(report: CompanyReport) -> CompanyReportOut:
    """The story report in the shared response models (company-report-spec contract)."""
    data = report.model_dump(mode="json")
    for ev in data["events"]:
        ev.setdefault("summary", "")
        ev["tone"] = ev.get("tone") or "neutral"
    for axis in data["profile"]["axes"]:
        for score in axis["scores"]:
            if score.get("trend") is not None:
                score["trend"]["delta"] = int(score["trend"].get("delta") or 0)
    data["summary"] = data.get("summary") or {"text": ""}
    data["warnings"] = data.get("warnings") or []
    return CompanyReportOut.model_validate(data)


def story_company_report(
    ctx: Ctx, ticker: str, *, models: ModelFactory | None = None
) -> CompanyReportOut | None:
    """The story report for the latest story run, or None when there is none to serve.

    None means: no story run, or cached mode and no report built for that run yet. Live mode builds
    and saves the report when a story run exists (one LLM call).
    """
    try:
        return _to_out(get_report(ctx, ticker, models=models))
    except NotCached:
        return None


def story_axis_detail(ctx: Ctx, ticker: str, axis_id: str, year: int | None) -> AxisDetailOut | None:
    """An axis detail from the saved story report, or None when no story report is saved.

    When one is saved, it alone answers: an axis or year it lacks is not found, never the ratio one.
    """
    cached = ctx.__class__(settings=ctx.settings, mode="cached", _store=ctx.store)
    try:
        saved, _ = build(cached, ticker)
    except NotCached:
        return None
    years = saved.report.years
    fy = year if year is not None else years[-1]
    if not any(a.id == axis_id for a in saved.report.profile.axes):
        raise AxisNotFound(f"{ticker.upper()}: no axis {axis_id!r} in the story report")
    if fy not in years:
        raise YearNotFound(
            f"{ticker.upper()}: no scores for {fy}; available years: {', '.join(map(str, years))}"
        )
    for d in saved.details:
        if d.axis_id == axis_id and d.fiscal_year == fy:
            return AxisDetailOut.model_validate(d.model_dump(mode="json"))
    raise AxisNotFound(f"{ticker.upper()}: the story report has no {axis_id!r} score for {fy}")
