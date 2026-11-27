"""State store interface (state-store spec, design D1).

Everything the server persists goes through a :class:`Store`: the provider and LLM
response caches, fetched report text with its metadata, financials snapshots, saved story
runs, and the usage logs. Two backends implement it: files under ``DATA_DIR`` (:mod:`.fs`) and Postgres
(:mod:`.pg`). Callers never build paths or SQL themselves.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from stock_analyzer.companies import TrackedCompany

Namespace = Literal["fr", "llm", "report"]
Source = Literal["fr", "llm"]
NAMESPACES: tuple[Namespace, ...] = ("fr", "llm", "report")


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

    def list_reports(self) -> list[tuple[str, int]]:
        """(ticker, fiscal year) of every stored report, sorted."""
        ...

    def save_financials(self, ticker: str, revisions: bool, data: Any) -> None: ...

    def save_story_run(self, ticker: str, run: Mapping[str, Any]) -> None:
        """Save one story run (a JSON-compatible dict with run_id, created_at, as_of and years)."""
        ...

    def latest_story_run(self, ticker: str) -> dict[str, Any] | None:
        """The most recently created story run for ``ticker``, exactly as saved."""
        ...

    def list_story_runs(self, ticker: str) -> list[dict[str, Any]]:
        """Summaries (run_id, created_at, as_of, years) of every saved run, newest first."""
        ...

    def log(self, source: Source, record: Mapping[str, Any]) -> None: ...

    def totals(self, source: Source) -> dict[str, Any]: ...

    # Companies added at runtime (the version-controlled list stays in companies.yaml).
    # Tickers are stored upper-case. ``add_tracked`` raises CompanyAlreadyTracked when the
    # ticker or provider id is already stored; ``remove_tracked`` returns False if absent.

    def list_tracked(self) -> list[TrackedCompany]: ...

    def add_tracked(self, company: TrackedCompany) -> None: ...

    def remove_tracked(self, ticker: str) -> bool: ...

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


def story_run_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    return {k: run.get(k) for k in ("run_id", "created_at", "as_of", "years")}
