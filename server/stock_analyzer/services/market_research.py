"""Resolve an issuer's industry and run or replay its market research brief."""

from __future__ import annotations

import asyncio
import re
from datetime import date

from stock_analyzer.config import MissingCredential
from stock_analyzer.errors import MissingSubIndustry, NotCached
from stock_analyzer.ingest.fr_client import FRClient
from stock_analyzer.llm import LLM, get_llm
from stock_analyzer.osint.blocklist import load_blocklist
from stock_analyzer.osint.market import (
    MARKET_NAMES,
    IndustryClass,
    Market,
    MarketResearchResult,
    research_markets,
)
from stock_analyzer.osint.models import RunState
from stock_analyzer.osint.search import FakeSearch, OpenRouterSearch, SearchBackend
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.osint import window_start
from stock_analyzer.store import StoreLog


def resolve_industry(client: FRClient, company_id: int, ticker: str) -> IndustryClass:
    profile = client.company_profile(company_id)
    if profile.id != company_id:
        raise ValueError(f"provider profile ID {profile.id} differs from requested ID {company_id}")
    code = profile.sub_industry_code
    if code is None or not re.fullmatch(r"[0-9]{4}", code):
        raise MissingSubIndustry(f"{ticker} has no valid ISIC Rev. 5 sub-industry code")
    return IndustryClass(code=code, name=profile.sub_industry.name if profile.sub_industry else None)


def run_market_research(
    ctx: Ctx,
    ticker: str,
    *,
    markets: list[str] | None = None,
    months: int | None = None,
    today: date | None = None,
    backend: SearchBackend | None = None,
    llm: LLM | None = None,
    test_industry: IndustryClass | None = None,
) -> MarketResearchResult:
    settings = ctx.settings
    months = settings.osint_window_months if months is None else months
    if months < 1:
        raise ValueError("months must be at least 1")
    requested = {market.strip().upper() for market in markets} if markets else set(MARKET_NAMES)
    if unknown := requested.difference(MARKET_NAMES):
        raise ValueError(f"unknown markets: {', '.join(sorted(unknown))}; choose IL, EUROPE, or US")
    selected: tuple[Market, ...] = tuple(market for market in MARKET_NAMES if market in requested)
    company = resolve_company(ctx, ticker)
    fake = settings.llm_fake
    if test_industry is not None and not fake:
        raise ValueError("fixed industry metadata requires offline test mode")

    namespace = "market-research-fake" if fake else "market-research"
    key = f"{namespace}:{company.ticker}:{','.join(selected)}:{months}m:latest"
    cache = ctx.store.cache("llm")
    if ctx.mode == "cached":
        raw = cache.get(key)
        if raw is None:
            raise NotCached(
                f"no stored market research for {company.ticker}, {', '.join(selected)}, {months} months"
            )
        return MarketResearchResult.model_validate(raw).model_copy(update={"from_cache": True})

    if test_industry is not None:
        industry = test_industry
    elif fake:
        with FRClient(settings, mode="cached", store=ctx.store) as client:
            industry = resolve_industry(client, company.fr_company_id, company.ticker)
    else:
        industry = resolve_industry(ctx.fr, company.fr_company_id, company.ticker)
    if not fake and settings.openrouter_api_key is None and (backend is None or llm is None):
        raise MissingCredential("OPENROUTER_API_KEY", "Market research")

    today = today or date.today()
    state = RunState(
        ticker=company.ticker,
        company_names=[],
        window_start=window_start(today, months),
        blocklist=load_blocklist(company.ticker),
        max_searches=settings.osint_max_searches,
        results_per_search=settings.osint_search_results,
    )
    briefs = asyncio.run(
        research_markets(
            state,
            industry,
            selected,
            today,
            backend if backend is not None else (FakeSearch() if fake else OpenRouterSearch(settings)),
            llm if llm is not None else get_llm(settings, store=ctx.store),
            StoreLog(ctx.store, "llm"),
        )
    )
    result = MarketResearchResult(
        ticker=company.ticker,
        industry=industry,
        markets=briefs,
        run_date=today,
        window_start=state.window_start,
        window_months=months,
        searches_used=state.searches_used,
        search_limit=state.max_searches,
    )
    cache.set(key, result.model_dump(mode="json"))
    return result
