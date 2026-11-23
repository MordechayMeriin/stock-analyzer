from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.services import companies, filings, financials
from stock_analyzer.services.models import (
    AddCompanyIn,
    CompanyOut,
    CompanySearchHit,
    FilingsOut,
    FinancialsOut,
)

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
