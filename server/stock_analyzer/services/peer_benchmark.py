"""Peer benchmark: a company's ratios beside its peers' ratios and per-market medians (peer-benchmark spec).

Peers come from the company's curated list when it has one, otherwise from the exact ISIC sub-industry
match, searched separately in each market cohort. Every peer's ratios come from the same engine as the
company's own (``ratios.analyze_id``), using its own statement template. Ratios are unit-free, so
currencies are reported but never converted; amount-unit series are left out.

``benchmark`` never calls a provider for data that is not stored in cached mode. ``live_run`` first
estimates the credits for what is missing and fetches only when confirmed, up to ``max_fetch`` financials.
"""

from __future__ import annotations

from decimal import Decimal
from statistics import median
from typing import Literal

from pydantic import BaseModel, Field

from stock_analyzer.companies import TrackedCompany
from stock_analyzer.errors import LiveModeRequired, NotCached, TemplateNotSupported
from stock_analyzer.ingest.fr_client import FRClient
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.peers import DOMESTIC_MARKET, eligible_peers
from stock_analyzer.services.ratios import RATIO_QUANTUM, Analysis, analyze_id, dec

# Market cohorts, Israel first. A curated peer outside every market gets a cohort named by its country.
MARKETS: dict[str, list[str]] = {
    DOMESTIC_MARKET: [DOMESTIC_MARKET],
    "US": ["US"],
    "EU": ["GB", "FR", "DE", "NL", "ES", "IT", "IE"],
}
MARKET_LABELS_HE = {DOMESTIC_MARKET: "ישראל", "US": "ארה״ב", "EU": "אירופה"}
FALLBACK_LIMIT = 5  # peers per market cohort for the sub-industry match
FINANCIALS_CREDITS = 40

PeerStatus = Literal["ok", "financials_not_cached", "template_not_supported", "other_template"]


class BenchRatioOut(BaseModel):
    code: str
    name_he: str
    group: str
    unit: Literal["percent", "ratio", "days"]
    direction: Literal["higher", "lower", "neutral"]


class BenchCompanyOut(BaseModel):
    id: int
    name: str
    ticker: str | None = None
    country: str | None = None
    status: PeerStatus = "ok"
    template: str | None = None
    currency: str | None = None
    fiscal_year: int | None = None  # the year the values are from (the company's latest)
    values: dict[str, str | None] = {}  # ratio code → exact decimal string (fraction for percent)
    in_median: bool = False


class MedianOut(BaseModel):
    value: str | None
    n: int


class CohortOut(BaseModel):
    market: str
    label_he: str
    countries: list[str]
    source: Literal["curated", "sub_industry"]
    reason: str | None = None  # e.g. no_matches
    peers: list[BenchCompanyOut]
    medians: dict[str, MedianOut]


class PeerBenchmarkOut(BaseModel):
    ticker: str
    match_parameter: Literal["curated", "sub_industry"] = Field(
        description="curated: the company's hand-picked peer list; sub_industry: exact ISIC class match"
    )
    sub_industry: str | None = None  # the target's ISIC class code, when its profile is stored
    sub_industry_label: str | None = None
    reason: str | None = None  # missing_sub_industry
    company: BenchCompanyOut
    ratios: list[BenchRatioOut]
    cohorts: list[CohortOut]


class PeerBenchmarkRunIn(BaseModel):
    confirm: bool = False
    max_fetch: int = Field(5, ge=1, le=12, description="Most financials requests (40 credits each) per run")


class PeerBenchmarkRunOut(BaseModel):
    financials_requests: int = Field(description="Peers whose financials are not stored")
    metadata_requests: int = Field(description="Profile/directory requests still needed (1 credit each)")
    estimated_credits: int
    fetched: list[int] = []  # provider IDs whose financials this run fetched
    benchmark: PeerBenchmarkOut | None = None  # only after a confirmed run


# ------------------------------------------------------------------ selection


class _Candidate(BaseModel):
    id: int
    name: str
    ticker: str | None = None
    country: str | None = None


class _Plan(BaseModel):
    source: Literal["curated", "sub_industry"]
    code: str | None = None
    label: str | None = None
    reason: str | None = None
    cohorts: list[tuple[str, list[str], list[_Candidate]]] = []


def market_of(country: str | None) -> str:
    for market, countries in MARKETS.items():
        if country in countries:
            return market
    return country or "??"


def _profile(ctx: Ctx, company_id: int, *, required: bool):
    try:
        return ctx.fr.company_profile(company_id)
    except NotCached:
        if required:
            raise
        return None


def plan(ctx: Ctx, company: TrackedCompany) -> _Plan:
    """Which peers to compare against, per market cohort. Raises NotCached when the match needs
    provider data that is not stored (cached mode)."""
    if company.peers:
        profile = _profile(ctx, company.fr_company_id, required=False)
        grouped: dict[str, list[_Candidate]] = {m: [] for m in MARKETS}
        for peer in company.peers:
            grouped.setdefault(market_of(peer.country), []).append(
                _Candidate(id=peer.fr_company_id, name=peer.name, country=peer.country)
            )
        return _Plan(
            source="curated",
            code=profile.sub_industry_code if profile else None,
            label=_label(profile),
            cohorts=[(m, MARKETS.get(m, [m]), ps) for m, ps in grouped.items() if ps],
        )
    profile = _profile(ctx, company.fr_company_id, required=True)
    code = profile.sub_industry_code
    if not code:
        return _Plan(source="sub_industry", reason="missing_sub_industry")
    cohorts = []
    for market, countries in MARKETS.items():
        rows = eligible_peers(ctx, countries, code, {company.fr_company_id})[:FALLBACK_LIMIT]
        cohorts.append(
            (
                market,
                countries,
                [_Candidate(id=r.id, name=r.name, ticker=r.ticker, country=r.country_code) for r in rows],
            )
        )
    return _Plan(source="sub_industry", code=code, label=_label(profile), cohorts=cohorts)


def _label(profile) -> str | None:
    sub = getattr(profile, "sub_industry", None) if profile else None
    return getattr(sub, "name", None) if sub else None


# ------------------------------------------------------------------ ratios and medians


def _bench_ratios(a: Analysis) -> list[BenchRatioOut]:
    return [
        BenchRatioOut(code=s.code, name_he=s.name_he, group=s.group, unit=s.unit, direction=s.direction)
        for s in a.series
        if s.unit != "amount"
    ]


def _row(base: BenchCompanyOut, a: Analysis, codes: set[str]) -> BenchCompanyOut:
    year = a.years[0] if a.years else None
    values = {}
    if year is not None:
        for s in a.series:
            if s.code in codes and year in s.values:
                values[s.code] = dec(s.values[year].value, RATIO_QUANTUM)
    return base.model_copy(
        update={"template": a.template, "currency": a.currency, "fiscal_year": year, "values": values}
    )


def _peer_row(ctx: Ctx, c: _Candidate, target: Analysis, codes: set[str]) -> BenchCompanyOut:
    base = BenchCompanyOut(id=c.id, name=c.name, ticker=c.ticker, country=c.country)
    try:
        a = analyze_id(ctx, c.id, c.name)
    except NotCached:
        return base.model_copy(update={"status": "financials_not_cached"})
    except TemplateNotSupported:
        return base.model_copy(update={"status": "template_not_supported"})
    row = _row(base, a, codes)
    if a.template != target.template:
        return row.model_copy(update={"status": "other_template"})
    near = row.fiscal_year is not None and target.years and abs(row.fiscal_year - target.years[0]) <= 1
    return row.model_copy(update={"in_median": bool(near)})


def medians(rows: list[BenchCompanyOut], codes: list[str]) -> dict[str, MedianOut]:
    out = {}
    for code in codes:
        xs = [Decimal(v) for r in rows if r.in_median and (v := r.values.get(code)) is not None]
        out[code] = MedianOut(value=dec(median(xs), RATIO_QUANTUM) if xs else None, n=len(xs))
    return out


def benchmark(ctx: Ctx, ticker: str) -> PeerBenchmarkOut:
    company = resolve_company(ctx, ticker)
    target = analyze_id(ctx, company.fr_company_id, company.ticker)
    ratios = _bench_ratios(target)
    codes = [r.code for r in ratios]
    p = plan(ctx, company)
    cohorts = []
    for market, countries, candidates in p.cohorts:
        rows = [_peer_row(ctx, c, target, set(codes)) for c in candidates]
        cohorts.append(
            CohortOut(
                market=market,
                label_he=MARKET_LABELS_HE.get(market, market),
                countries=countries,
                source=p.source,
                reason=None if rows else "no_matches",
                peers=rows,
                medians=medians(rows, codes),
            )
        )
    head = BenchCompanyOut(
        id=company.fr_company_id, name=company.name_en or company.name_he, ticker=company.ticker, country="IL"
    )
    return PeerBenchmarkOut(
        ticker=company.ticker,
        match_parameter=p.source,
        sub_industry=p.code,
        sub_industry_label=p.label,
        reason=p.reason,
        company=_row(head, target, set(codes)),
        ratios=ratios,
        cohorts=cohorts,
    )


# ------------------------------------------------------------------ live run


def _financials_cached(fr: FRClient, company_id: int) -> bool:
    return fr.is_cached(f"/companies/{company_id}/financials/", {"fiscal_period": "FY"})


def _missing(ctx: Ctx, company: TrackedCompany) -> tuple[list[int], int]:
    """(peer IDs without stored financials, metadata requests still needed) from stored data only."""
    cached = Ctx(ctx.settings, mode="cached")
    try:
        try:
            p = plan(cached, company)
        except NotCached:
            # Profile or directory pages missing: one profile request and about one page per market.
            return [], 1 + len(MARKETS)
        ids = [c.id for _, _, cs in p.cohorts for c in cs]
        if not _financials_cached(cached.fr, company.fr_company_id):
            ids.insert(0, company.fr_company_id)
        return [i for i in ids if not _financials_cached(cached.fr, i)], 0
    finally:
        cached.close()


def live_run(ctx: Ctx, ticker: str, body: PeerBenchmarkRunIn) -> PeerBenchmarkRunOut:
    company = resolve_company(ctx, ticker)
    if ctx.mode != "live":
        raise LiveModeRequired("a peer-benchmark run fetches provider data; switch the client to live")
    missing, meta = _missing(ctx, company)
    estimate = PeerBenchmarkRunOut(
        financials_requests=len(missing),
        metadata_requests=meta,
        estimated_credits=FINANCIALS_CREDITS * min(len(missing), body.max_fetch) + meta,
    )
    if not body.confirm:
        return estimate
    if meta:  # fetch the cheap profile/directory pages, then re-plan against them
        plan(ctx, company)
        missing, _ = _missing(ctx, company)
    fetched = []
    for company_id in missing[: body.max_fetch]:
        ctx.fr.get_financials(company_id)
        fetched.append(company_id)
    cached = Ctx(ctx.settings, mode="cached")
    try:
        result = benchmark(cached, company.ticker)
    finally:
        cached.close()
    return estimate.model_copy(update={"fetched": fetched, "benchmark": result})
