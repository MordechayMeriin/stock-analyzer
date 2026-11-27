from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Query, Response, status

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.diff.align import Comparison
from stock_analyzer.services import companies, compare, filings, financials, peer_benchmark, ratios
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import (
    AddCompanyIn,
    CompanyOut,
    CompanySearchHit,
    FilingsOut,
    FinancialsOut,
    RatiosOut,
)
from stock_analyzer.services.peer_benchmark import PeerBenchmarkOut, PeerBenchmarkRunIn, PeerBenchmarkRunOut

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut], summary="Tracked companies")
def list_companies(ctx: CtxDep) -> list[CompanyOut]:
    return companies.list_tracked(ctx)


@router.post(
    "",
    response_model=CompanyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start tracking a company (live mode only)",
    description="Adds a provider company to the tracked companies. Refused in cached mode (`live_required`), "
    "on a cached-only server (`live_disabled`) and when the ticker or provider id is already tracked "
    "(`company_already_tracked`). Nothing is fetched from the provider.",
)
def add_company(ctx: CtxDep, body: AddCompanyIn) -> CompanyOut:
    return companies.add(ctx, body)


@router.get("/search", response_model=list[CompanySearchHit], summary="Search provider companies (Israel)")
def search_companies(
    ctx: CtxDep, q: Annotated[str, Query(min_length=1, max_length=100)]
) -> list[CompanySearchHit]:
    return companies.search(ctx, q)


@router.get("/{ticker}", response_model=CompanyOut, summary="One tracked company")
def get_company(ctx: CtxDep, ticker: str) -> CompanyOut:
    return companies.get_company(ctx, ticker)


@router.delete(
    "/{ticker}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Stop tracking a runtime-added company (live mode only)",
    description="Companies from data/companies.yaml cannot be removed (`company_not_removable`). "
    "Cached reports, financials and usage records are kept.",
)
def remove_company(ctx: CtxDep, ticker: str) -> Response:
    companies.remove(ctx, ticker)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{ticker}/filings", response_model=FilingsOut, summary="Annual filings with the selected report per year"
)
def list_filings(ctx: CtxDep, ticker: str) -> FilingsOut:
    return filings.list_filings(ctx, ticker)


@router.get(
    "/{ticker}/financials",
    response_model=FinancialsOut,
    summary="Normalized financials by statement and year",
)
def get_financials(
    ctx: CtxDep,
    ticker: str,
    as_of: Annotated[date | None, Query(description="Only values available by this date")] = None,
) -> FinancialsOut:
    return financials.financials(ctx, ticker, as_of=as_of)


@router.get(
    "/{ticker}/ratios",
    response_model=RatiosOut,
    summary="Financial ratios by group and year, with confidence and data-quality checks",
)
def get_ratios(
    ctx: CtxDep,
    ticker: str,
    as_of: Annotated[date | None, Query(description="Only values available by this date")] = None,
) -> RatiosOut:
    return ratios.ratios(ctx, ticker, as_of=as_of)


@router.get(
    "/{ticker}/peer-benchmark",
    response_model=PeerBenchmarkOut,
    summary="Ratios beside listed peers and per-market medians (stored data only, never calls a provider)",
    description="Peers come from the company's curated list, or else the exact ISIC sub-industry match per "
    "market (Israel, US, Europe). Peers without stored financials are listed as `financials_not_cached`. "
    "`not_cached` (409) when the company's financials, profile or peer directory are not stored.",
)
def get_peer_benchmark(ctx: CtxDep, ticker: str) -> PeerBenchmarkOut:
    cached = Ctx(ctx.settings, mode="cached")
    try:
        return peer_benchmark.benchmark(cached, ticker)
    finally:
        cached.close()


@router.post(
    "/{ticker}/peer-benchmark",
    response_model=PeerBenchmarkRunOut,
    summary="Estimate, then fetch, what the peer benchmark is missing (live mode)",
    description="Without `confirm` it only reports the requests and estimated credits (financials cost 40 "
    "each). With `confirm` it fetches up to `max_fetch` missing financials and returns the benchmark. "
    "Refused with `live_required` in cached mode or `live_disabled` on a cached-only server.",
)
def run_peer_benchmark(
    ctx: CtxDep, ticker: str, body: Annotated[PeerBenchmarkRunIn | None, Body()] = None
) -> PeerBenchmarkRunOut:
    return peer_benchmark.live_run(ctx, ticker, body or PeerBenchmarkRunIn())


@router.get(
    "/{ticker}/compare",
    response_model=Comparison,
    summary="Business sections aligned across fiscal years, with a change status per year pair",
)
def get_comparison(
    ctx: CtxDep,
    ticker: str,
    years: Annotated[
        list[int], Query(min_length=2, description="Fiscal years to compare (repeat the parameter)")
    ],
) -> Comparison:
    return compare.compare(ctx, ticker, years)
