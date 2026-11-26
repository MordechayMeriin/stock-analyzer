"""OSINT research service (osint-research spec, design D6, D10).

``run_research`` resolves a tracked company and, in live mode, always researches it afresh and stores the
result as the latest one for that ticker and window. When live calls are disabled (or the context is in
cached mode) it serves the latest stored result instead, and fails if there is none. Results live in the
state store's ``llm`` cache namespace under ``osint:`` keys, so the database schema does not change.
Nothing here reads filings, reports or financials.
"""

from __future__ import annotations

import asyncio
import calendar
from datetime import date

from stock_analyzer.errors import LiveModeDisabled, NotCached
from stock_analyzer.osint.agents import ModelFactory, fake_model_factory, live_model_factory, run_pipeline
from stock_analyzer.osint.blocklist import load_blocklist
from stock_analyzer.osint.models import ResearchResult, RunState
from stock_analyzer.osint.search import FakeSearch, OpenRouterSearch, SearchBackend
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.store import StoreLog


def window_start(today: date, months: int) -> date:
    """``today`` minus ``months`` calendar months (the day is clamped to the month's length)."""
    total = today.year * 12 + (today.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def cache_key(ticker: str, months: int, *, fake: bool = False) -> str:
    """Key of the latest result. Fake-mode results get their own prefix so they are never served as real."""
    prefix = "osint-fake" if fake else "osint"
    return f"{prefix}:{ticker.upper()}:{months}m:latest"


def cached_result(ctx: Ctx, ticker: str, months: int) -> ResearchResult | None:
    """The latest stored result for this ticker and window, if any."""
    key = cache_key(ticker, months, fake=ctx.settings.llm_fake)
    raw = ctx.store.cache("llm").get(key)
    if raw is None:
        return None
    result = ResearchResult.model_validate(raw)
    result.from_cache = True
    return result


def run_research(
    ctx: Ctx,
    ticker: str,
    months: int | None = None,
    *,
    today: date | None = None,
    backend: SearchBackend | None = None,
    model_factory: ModelFactory | None = None,
) -> ResearchResult:
    settings = ctx.settings
    months = months or settings.osint_window_months
    if months < 1:
        raise ValueError("months must be at least 1")
    today = today or date.today()
    company = resolve_company(ctx, ticker)  # an untracked ticker fails here, before any provider call
    ticker = company.ticker

    fake = settings.llm_fake
    live = fake or (settings.allow_live and ctx.mode == "live")
    if not live:  # no provider call allowed: the latest stored result, or a clear refusal
        if (stored := cached_result(ctx, ticker, months)) is not None:
            return stored
        if not settings.allow_live:
            raise LiveModeDisabled(
                f"live calls are disabled on this server (ALLOW_LIVE=false) and no stored OSINT result "
                f"exists for {ticker} ({months} months)"
            )
        raise NotCached(
            f"no stored OSINT result for {ticker} ({months} months); run in live mode to research it"
        )

    names = list(
        dict.fromkeys(n.strip() for n in (company.name_he, company.name_en or "") if n and n.strip())
    )
    state = RunState(
        ticker=ticker,
        company_names=names,
        window_start=window_start(today, months),
        blocklist=load_blocklist(ticker),
        max_searches=settings.osint_max_searches,
        results_per_search=settings.osint_search_results,
    )
    backend = backend or (FakeSearch() if fake else OpenRouterSearch(settings))
    model_factory = model_factory or (fake_model_factory(ticker) if fake else live_model_factory(settings))
    log = StoreLog(ctx.store, "llm")

    scorecard, kept, dropped = asyncio.run(
        run_pipeline(settings, state, backend=backend, log=log, model_factory=model_factory, today=today)
    )
    result = ResearchResult(
        ticker=ticker,
        company_name=" / ".join(names),
        run_date=today,
        window_months=months,
        window_start=state.window_start,
        model=f"fake/{settings.model_osint}" if fake else settings.model_osint,
        scorecard=scorecard,
        findings=kept,
        dropped=dropped,
        searches_used=state.searches_used,
        search_limit=state.max_searches,
        cost_usd=round(state.cost_usd, 6) if state.cost_known else None,
    )
    ctx.store.cache("llm").set(cache_key(ticker, months, fake=fake), result.model_dump(mode="json"))
    return result
