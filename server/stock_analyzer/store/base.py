"""State store interface (state-store spec, design D1).

Everything the server persists goes through a :class:`Store`: the provider and LLM
response caches, fetched report text with its metadata, financials snapshots, and the
usage logs. Two backends implement it: files under ``DATA_DIR`` (:mod:`.fs`) and Postgres
(:mod:`.pg`). Callers never build paths or SQL themselves.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

Namespace = Literal["fr", "llm"]
Source = Literal["fr", "llm"]
NAMESPACES: tuple[Namespace, ...] = ("fr", "llm")


class ReportMeta(BaseModel):
    """Metadata saved next to a fetched report's Markdown."""

    ticker: str
    fiscal_year: int
    filing_id: int
    title: str
    document_url: str | None
    release_datetime: datetime | None
    total_chars: int
    sha256: str
    fetched_at: str


class KVCache(Protocol):
    """A permanent key-value cache. Values are JSON-compatible (dicts or strings)."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...

    def delete(self, key: str) -> None: ...

    def __contains__(self, key: object) -> bool: ...


class Store(Protocol):
    backend: Literal["fs", "postgres"]

    def cache(self, namespace: Namespace) -> KVCache: ...

    def save_report(self, ticker: str, fiscal_year: int, meta: ReportMeta, text: str) -> None: ...

    def load_report(self, ticker: str, fiscal_year: int) -> tuple[str, ReportMeta] | None: ...

    def cached_filing_id(self, ticker: str, fiscal_year: int) -> int | None: ...

    def report_location(self, ticker: str, fiscal_year: int) -> str: ...

    def save_financials(self, ticker: str, revisions: bool, data: Any) -> None: ...

    def log(self, source: Source, record: Mapping[str, Any]) -> None: ...

    def totals(self, source: Source) -> dict[str, Any]: ...

    def ping(self) -> bool: ...

    def close(self) -> None: ...


class StoreLog:
    """Append-only usage log for one source, timestamped. Never receives prompts or credentials."""

    def __init__(self, store: Store, source: Source):
        self.store = store
        self.source = source

    def write(self, **record: Any) -> None:
        self.store.log(self.source, {"ts": datetime.now(UTC).isoformat(), **record})


# ---------------------------------------------------------------- totals (shared semantics)


def fr_totals(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Credit totals over provider log records, for the usage endpoint."""
    calls = hits = credits = 0
    for rec in records:
        calls += 1
        hits += rec.get("cache") == "hit"
        credits += int(rec.get("credits") or 0)
    return {"calls": calls, "cache_hits": hits, "network_calls": calls - hits, "credits_logged": credits}


def llm_totals(records: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
    """Totals over LLM log records, for the usage endpoint."""
    calls = cache_hits = failures = 0
    cost = 0.0
    for rec in records:
        calls += 1
        cache_hits += bool(rec.get("cache_hit"))
        failures += not rec.get("ok", True)
        cost += float(rec.get("cost") or 0)
    return {"calls": calls, "cache_hits": cache_hits, "failures": failures, "total_cost_usd": round(cost, 6)}
