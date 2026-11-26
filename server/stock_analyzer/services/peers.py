"""Select listed peers by exact ISIC class, searching Israel before optional foreign markets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.ingest.fr_client import CompanyProfile
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.financials import annual_statements
from stock_analyzer.services.models import FinStatementOut

DOMESTIC_MARKET = "IL"


@dataclass
class PeerSelection:
    target: CompanyProfile
    peer_countries: list[str]
    domestic_count: int | None
    reason: str | None
    peers: list[CompanyProfile]


class PeerOut(BaseModel):
    id: int
    name: str
    ticker: str | None
    country: str
    kind: Literal["domestic", "international"]
    currency: str | None
    years: list[int]
    statements: list[FinStatementOut]
    available_at: dict[str, str | None]


class PeerFinancialsOut(BaseModel):
    target_id: int
    target_country: str | None
    domestic_market: str = DOMESTIC_MARKET
    sub_industry: str | None
    peer_countries: list[str]
    domestic_count: int | None
    reason: str | None
    peers: list[PeerOut]


def eligible_peers(ctx: Ctx, countries: list[str], code: str, exclude_ids: set[int]) -> list[CompanyProfile]:
    by_id = {
        row.id: row
        for row in ctx.fr.list_peer_candidates(countries, code)
        if row.id not in exclude_ids
        and row.country_code in countries
        and row.listing_status == "LISTED"
        and row.sub_industry_code == code
    }
    return [by_id[key] for key in sorted(by_id)]


def select_peers(ctx: Ctx, ticker: str, limit: int, peer_countries: list[str]) -> PeerSelection:
    if limit < 1:
        raise ValueError("limit must be positive")
    countries = {country.strip().upper() for country in peer_countries}
    if any(len(code) != 2 or not code.isascii() or not code.isalpha() for code in countries):
        raise ValueError("peer countries must be two-letter country codes")
    foreign = sorted(countries - {DOMESTIC_MARKET})
    company = resolve_company(ctx, ticker)
    target = ctx.fr.company_profile(company.fr_company_id)
    if target.id != company.fr_company_id:
        raise ValueError(f"provider profile ID {target.id} differs from requested ID {company.fr_company_id}")
    code = target.sub_industry_code
    if not code:
        return PeerSelection(target, foreign, None, "missing_sub_industry", [])

    domestic = eligible_peers(ctx, [DOMESTIC_MARKET], code, {target.id})
    selected = domestic[:limit]
    if foreign and len(selected) < limit:
        excluded = {peer.id for peer in selected} | {target.id}
        international = eligible_peers(ctx, foreign, code, excluded)
        selected.extend(international[: limit - len(selected)])
    return PeerSelection(
        target, foreign, len(domestic), None if domestic else "no_domestic_matches", selected
    )


def peer_financials(ctx: Ctx, ticker: str, limit: int, peer_countries: list[str]) -> PeerFinancialsOut:
    selection = select_peers(ctx, ticker, limit, peer_countries)
    target = selection.target
    return PeerFinancialsOut(
        target_id=target.id,
        target_country=target.country_code,
        sub_industry=target.sub_industry_code,
        peer_countries=selection.peer_countries,
        domestic_count=selection.domestic_count,
        reason=selection.reason,
        peers=[
            PeerOut(
                id=peer.id,
                name=peer.name,
                ticker=peer.ticker,
                country=peer.country_code,
                kind="domestic" if peer.country_code == DOMESTIC_MARKET else "international",
                **annual_statements(ctx, peer.id),
            )
            for peer in selection.peers
        ],
    )
