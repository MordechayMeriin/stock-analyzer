"""OSINT stability research endpoints (osint-research spec, analyzer-api spec: OSINT endpoints)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.osint.models import ResearchResult
from stock_analyzer.services import osint
from stock_analyzer.services.companies import require_live

router = APIRouter(prefix="/api/companies/{ticker}/osint", tags=["osint"])

Months = Annotated[
    int | None,
    Query(
        ge=1,
        le=120,
        description="Research window in months. Defaults to the server's OSINT_WINDOW_MONTHS (36).",
    ),
]


@router.get(
    "",
    response_model=ResearchResult,
    summary="Latest stored OSINT stability scorecard",
    description="Returns the latest stored research result for the ticker and window. Never searches the web "
    "or calls an LLM, in any mode. Fails with 409 `not_cached` when the company has not been researched yet.",
)
def get_research(ctx: CtxDep, ticker: str, months: Months = None) -> ResearchResult:
    return osint.latest_research(ctx, ticker, months)


@router.post(
    "",
    response_model=ResearchResult,
    summary="Run OSINT stability research (live mode only)",
    description="Researches the company afresh from open sources (never its official filings), stores the "
    "result as the latest one and returns it. Spends LLM and web-search credit and takes minutes. Refused in "
    "cached mode (`live_required`) and on a cached-only server (`live_disabled`). A run whose findings all "
    "fail verification fails with 422 `osint_no_findings`.",
)
def run_research(ctx: CtxDep, ticker: str, months: Months = None) -> ResearchResult:
    require_live(ctx, "OSINT research")
    return osint.run_research(ctx, ticker, months)
