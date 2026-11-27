"""Ticker autocomplete over a stored directory of listed companies (free, local, cached-only).

The directory is the provider's paged ``/companies/`` listing (1 credit per page of 100), fetched
only by :func:`refresh_directory`. Searching reads the cache and never calls the network.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

from stock_analyzer.errors import NotCached
from stock_analyzer.ingest.fr_client import CompanyDirectoryPage, FRClient
from stock_analyzer.services import companies
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import TickerDirectoryInfo, TickerHit, TickerSearchOut

MEMO_TTL_S = 600.0
_HEBREW = re.compile("[֐-׿]")
_QUOTES = re.compile("[\"'`׳״‘’“”]")
_PUNCT = re.compile(r"[.\-־_,]")
_SUFFIX = re.compile(r"\s+(?:בעמ|ltd|limited)$")


@dataclass(frozen=True)
class DirectoryEntry:
    ticker: str
    name: str
    isin: str | None
    fr_company_id: int
    name_he: str | None = None
    name_en: str | None = None


@dataclass
class _Directory:
    entries: list[DirectoryEntry]
    fetched_at: str | None


_memo: dict[tuple[str, str], tuple[float, _Directory | None]] = {}
_lock = threading.Lock()


def _memo_key(ctx: Ctx) -> tuple[str, str]:
    return (str(ctx.settings.data_dir), ctx.settings.fr_country)


def clear_memo() -> None:
    with _lock:
        _memo.clear()


def normalize(text: str) -> str:
    t = _QUOTES.sub("", text.casefold())
    t = _PUNCT.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return _SUFFIX.sub("", t).strip()


def _load(ctx: Ctx) -> _Directory | None:
    # Always a cached-mode client on the same store: a miss raises NotCached, never a network call.
    client = FRClient(ctx.settings, mode="cached", store=ctx.store)
    country = ctx.settings.fr_country
    entries: list[DirectoryEntry] = []
    page = 1
    while True:
        try:
            response = client.request("/companies/", client.listing_params(country, page))
        except NotCached:
            if page == 1:
                return None
            break
        data = CompanyDirectoryPage.model_validate_json(response.body)
        for p in data.results:
            ticker = (p.ticker or "").strip().upper()
            if not ticker:
                continue
            has_he = bool(_HEBREW.search(p.name))
            entries.append(
                DirectoryEntry(
                    ticker=ticker,
                    name=p.name,
                    isin=p.isin,
                    fr_company_id=p.id,
                    name_he=p.name if has_he else None,
                    name_en=None if has_he else p.name,
                )
            )
        if not data.next:
            break
        page += 1
    fetched = client.cached_at("/companies/", client.listing_params(country, 1))
    return _Directory(entries, fetched.isoformat() if fetched else None)


def _directory(ctx: Ctx) -> _Directory | None:
    key = _memo_key(ctx)
    now = time.monotonic()
    with _lock:
        hit = _memo.get(key)
        if hit and now - hit[0] < MEMO_TTL_S:
            return hit[1]
    loaded = _load(ctx)
    with _lock:
        _memo[key] = (now, loaded)
    return loaded


def directory(ctx: Ctx) -> list[DirectoryEntry] | None:
    """Stored directory entries, or None when page 1 is not stored. Never touches the network."""
    d = _directory(ctx)
    return None if d is None else d.entries


def directory_info(ctx: Ctx) -> TickerDirectoryInfo:
    d = _directory(ctx)
    if d is None:
        return TickerDirectoryInfo(size=0, source="tracked_only")
    return TickerDirectoryInfo(size=len(d.entries), fetched_at=d.fetched_at, source="directory")


def refresh_directory(ctx: Ctx) -> tuple[int, int]:
    """Re-fetch every listing page (live mode; spends credits). Returns (companies, credits used)."""
    companies.require_live(ctx, "refreshing the ticker directory")
    client = FRClient(ctx.settings, mode="live", store=ctx.store)
    rows = client.list_listed_companies(refresh=True)
    clear_memo()
    return len(rows), client.credits_used


def _rank(q: str, ticker: str, name: str) -> int | None:
    if ticker == q:
        return 0
    if ticker.startswith(q):
        return 1
    if len(q) < 2:
        return None
    if name.startswith(q):
        return 2
    if any(w.startswith(q) for w in name.split()):
        return 3
    if q in name:
        return 4
    return None


def search(ctx: Ctx, q: str, limit: int = 8) -> TickerSearchOut:
    limit = max(1, min(limit, 20))
    d = _directory(ctx)
    registry = companies.registry(ctx)
    by_id = {c.fr_company_id: c for c in registry}
    by_ticker = {c.ticker.upper(): c for c in registry}

    hits: dict[str, tuple[TickerHit, list[str]]] = {}  # ticker -> (hit, normalised names)
    for e in d.entries if d else []:
        if by_id.get(e.fr_company_id) or by_ticker.get(e.ticker):
            continue
        hits[e.ticker] = (
            TickerHit(
                ticker=e.ticker,
                name_he=e.name_he or e.name,
                name_en=e.name_en,
                fr_company_id=e.fr_company_id,
                isin=e.isin,
                tracked=False,
            ),
            [normalize(e.name)],
        )
    for c in registry:
        hits[c.ticker.upper()] = (
            TickerHit(
                ticker=c.ticker.upper(),
                name_he=c.name_he,
                name_en=c.name_en,
                fr_company_id=c.fr_company_id,
                isin=c.isin,
                tracked=True,
            ),
            [normalize(n) for n in (c.name_he, c.name_en) if n],
        )
    for e in d.entries if d else []:  # a tracked company's provider name is searchable too
        t = by_id.get(e.fr_company_id) or by_ticker.get(e.ticker)
        if t:
            hits[t.ticker.upper()][1].append(normalize(e.name))

    nq = normalize(q)
    ranked: list[tuple[tuple[int, int, int, str], TickerHit]] = []
    if nq:
        for ticker, (hit, names) in hits.items():
            ranks = [r for n in names if (r := _rank(nq, ticker.casefold(), n)) is not None]
            if not ranks and (r := _rank(nq, ticker.casefold(), "")) is not None:
                ranks = [r]
            if ranks:
                ranked.append(((min(ranks), 0 if hit.tracked else 1, len(hit.name_he), ticker), hit))
    ranked.sort(key=lambda r: r[0])
    return TickerSearchOut(results=[h for _, h in ranked[:limit]], directory=directory_info(ctx))
