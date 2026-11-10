"""Company services: tracked registry and provider search."""

from __future__ import annotations

from stock_analyzer.companies import TrackedCompany, load_companies, resolve_ticker
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import CompanyOut, CompanySearchHit


def _out(c: TrackedCompany) -> CompanyOut:
    return CompanyOut(**c.model_dump())


def list_tracked(ctx: Ctx) -> list[CompanyOut]:
    return [_out(c) for c in load_companies(ctx.settings.companies_file)]


def get_company(ctx: Ctx, ticker: str) -> CompanyOut:
    return _out(resolve_ticker(ctx.settings.companies_file, ticker))


def search(ctx: Ctx, query: str) -> list[CompanySearchHit]:
    tracked = {c.fr_company_id: c.ticker for c in load_companies(ctx.settings.companies_file)}
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
