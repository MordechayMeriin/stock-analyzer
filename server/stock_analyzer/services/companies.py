"""Company services: the tracked registry (YAML plus runtime-added), provider search, add/remove."""

from __future__ import annotations

from stock_analyzer.companies import TrackedCompany, find_duplicate, find_ticker, load_registry
from stock_analyzer.errors import (
    CompanyAlreadyTracked,
    CompanyNotFound,
    CompanyNotRemovable,
    LiveModeRequired,
)
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import AddCompanyIn, CompanyOut, CompanySearchHit


def _out(c: TrackedCompany) -> CompanyOut:
    return CompanyOut(**c.model_dump())


def registry(ctx: Ctx) -> list[TrackedCompany]:
    """Every tracked company: data/companies.yaml first, then the ones added at runtime."""
    return load_registry(ctx.settings.companies_file, ctx.store)


def resolve_company(ctx: Ctx, ticker: str) -> TrackedCompany:
    """The tracked company for a ticker (case-insensitive), from either source."""
    return find_ticker(registry(ctx), ticker)


def list_tracked(ctx: Ctx) -> list[CompanyOut]:
    return [_out(c) for c in registry(ctx)]


def get_company(ctx: Ctx, ticker: str) -> CompanyOut:
    return _out(resolve_company(ctx, ticker))


def search(ctx: Ctx, query: str) -> list[CompanySearchHit]:
    tracked = {c.fr_company_id: c.ticker for c in registry(ctx)}
    return [
        CompanySearchHit(
            fr_company_id=m.id,
            name=m.name,
            ticker=m.ticker,
            isin=m.isin,
            country_code=m.country_code,
            tracked_ticker=tracked.get(m.id),
        )
        for m in ctx.fr.search_companies(query)
    ]


def require_live(ctx: Ctx, action: str) -> None:
    """Registry edits are the first step towards spending credits, so they need live mode.

    A cached-only server already refused live mode when the context was built (live_disabled).
    """
    if ctx.mode != "live":
        raise LiveModeRequired(f"{action} needs live mode; switch the client to live and try again")


def add(ctx: Ctx, company: AddCompanyIn) -> CompanyOut:
    """Start tracking a company. Nothing is fetched from the provider."""
    require_live(ctx, "adding a company")
    candidate = TrackedCompany(**company.model_dump(), source="added")
    if (dup := find_duplicate(registry(ctx), candidate)) is not None:
        raise CompanyAlreadyTracked(
            f"ticker {candidate.ticker} or provider company {candidate.fr_company_id} is already tracked as {dup.ticker}"
        )
    ctx.store.add_tracked(candidate)
    return _out(candidate)


def remove(ctx: Ctx, ticker: str) -> None:
    """Stop tracking a runtime-added company. Its cached reports, financials and logs stay."""
    require_live(ctx, "removing a company")
    company = resolve_company(ctx, ticker)
    if company.source != "added":
        raise CompanyNotRemovable(
            f"{company.ticker} is in data/companies.yaml (version-controlled) and cannot be removed here"
        )
    if not ctx.store.remove_tracked(company.ticker):  # removed meanwhile by someone else
        raise CompanyNotFound(f"unknown ticker {ticker!r}: not in the tracked companies registry")
