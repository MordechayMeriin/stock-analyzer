"""FinancialFilings REST client (plan.md §1.1, filings-client spec, docs/fr_api.md).

- ``X-API-Key`` header from env only; the key never reaches logs, cache files or responses.
- Retries 429/5xx and transport errors with exponential backoff, honoring ``Retry-After``;
  other 4xx fail immediately.
- Permanent cache in the state store (files or Postgres, see ``stock_analyzer.store``), keyed by path + params (``refresh`` bypasses and overwrites it);
  ``mode="cached"`` never touches the network and raises :class:`NotCached` on a miss.
- One usage log record per call in the state store (cache hits included, at 0 credits).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from stock_analyzer.config import MissingCredential, Settings
from stock_analyzer.errors import NotCached, ProviderError, ProviderNotFound, TruncatedContent
from stock_analyzer.store import Store, StoreLog, fr_totals, get_store
from stock_analyzer.store.base import KVCache, ReportMeta
from stock_analyzer.store.fs import raw_paths, read_exact, read_jsonl

__all__ = [
    "FRClient",
    "ReportMeta",
    "load_report",
    "raw_paths",
    "read_exact",
    "read_fr_totals",
    "save_report",
]

Mode = Literal["live", "cached"]

# Documented prices (credits per call), used when X-Credits-Charged is absent.
CREDIT_PRICES: tuple[tuple[str, int], ...] = (
    ("/markdown/", 6),
    ("/financials/", 40),
    ("/usage/", 0),
    ("/companies/", 1),
    ("/filings/", 1),
)


def estimate_credits(path: str) -> int:
    for fragment, price in CREDIT_PRICES:
        if fragment in path:
            return price
    return 1


# ---------------------------------------------------------------- models (permissive)


class CompanyMatch(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    ticker: str | None = None
    isins: list[str] = []
    primary_isin: str | None = None
    country_code: str | None = None

    @property
    def isin(self) -> str | None:
        return self.primary_isin or (self.isins[0] if self.isins else None)


class Filing(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    title: str = ""
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    release_datetime: datetime | None = None
    file_extension: str | None = None
    file_size: int | None = None
    document: str | None = None  # file URL in the full view
    document_url: str | None = None  # file URL in the summary view
    viewer_url: str | None = None
    processing_status: str | None = None

    @property
    def url(self) -> str | None:
        return self.document or self.document_url


class FRResponse(BaseModel):
    """What the cache stores for one request: body plus the headers we use. No credentials."""

    status: int
    body: str
    total_chars: int | None = None
    next_offset: int | None = None
    credits: int | None = None
    fetched_at: str

    def json_body(self) -> Any:
        return json.loads(self.body)


def read_fr_totals(path: Path) -> dict[str, int]:
    """Credit totals from a JSONL fetch log file (file backend)."""
    return fr_totals(read_jsonl(path))


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            return max((parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds(), 0.0)
        except (TypeError, ValueError):
            return None


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            return str(data.get("detail") or data.get("type") or data)[:300]
    except ValueError:
        pass
    return response.text[:300]


# ---------------------------------------------------------------- client


class FRClient:
    def __init__(
        self,
        settings: Settings,
        *,
        mode: Mode = "live",
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        store: Store | None = None,
    ):
        if mode not in ("live", "cached"):
            raise ValueError(f"mode must be 'live' or 'cached', got {mode!r}")
        if mode == "cached" and refresh:
            raise ValueError("refresh needs live mode")
        self.settings = settings
        self.mode: Mode = mode
        self.refresh = refresh
        self._transport = transport
        self._sleep = sleep
        self._http: httpx.Client | None = None
        self._owns_store = store is None
        self.store: Store = store if store is not None else get_store(settings)
        self.log = StoreLog(self.store, "fr")
        self.credits_used = 0  # credits spent by this client instance (network calls only)
        self.network_calls = 0

    # -- plumbing

    @property
    def cache(self) -> KVCache:
        return self.store.cache("fr")

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            if self.settings.fr_api_key is None:
                raise MissingCredential("FR_API_KEY", "A live FinancialFilings call")
            self._http = httpx.Client(
                base_url=self.settings.fr_base_url,
                headers={
                    "X-API-Key": self.settings.fr_api_key.get_secret_value(),
                    "Accept": "application/json, text/markdown",
                    "User-Agent": "stock-analyzer/0.1",
                },
                timeout=self.settings.fr_timeout_s,
                transport=self._transport,
            )
        return self._http

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
        if self._owns_store:
            self.store.close()

    def __enter__(self) -> FRClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def cache_key(path: str, params: Mapping[str, Any] | None) -> str:
        items = sorted((str(k), str(v)) for k, v in (params or {}).items() if v is not None)
        return "fr:" + hashlib.sha256(json.dumps([path, items]).encode()).hexdigest()

    def is_cached(self, path: str, params: Mapping[str, Any] | None = None) -> bool:
        return self.cache_key(path, params) in self.cache

    def request(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        refresh: bool | None = None,
        cache: bool = True,
        validate: Callable[[FRResponse], None] | None = None,
    ) -> FRResponse:
        """GET ``path`` through the cache. ``validate`` runs before a response is cached."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        refresh = self.refresh if refresh is None else refresh
        key = self.cache_key(path, params)
        log_params = dict(params)

        if cache and not refresh:
            cached = self.cache.get(key)
            if cached is not None:
                self.log.write(
                    endpoint=path, params=log_params, status=cached["status"], cache="hit", credits=0
                )
                return FRResponse.model_validate(cached)

        if self.mode == "cached":
            raise NotCached(
                f"not cached: GET {path} {log_params or ''}".rstrip()
                + " (cached mode makes no provider calls)"
            )

        response = self._send(path, params, log_params, cache_state="refresh" if refresh else "miss")
        if validate is not None:
            validate(response)
        if cache:
            self.cache.set(key, response.model_dump())
        return response

    def _send(
        self, path: str, params: dict[str, Any], log_params: dict[str, Any], cache_state: str
    ) -> FRResponse:
        attempts = max(self.settings.fr_max_attempts, 1)
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                response = self.http.get(path, params=params)
            except httpx.TransportError as exc:
                self.log.write(
                    endpoint=path,
                    params=log_params,
                    status=None,
                    cache=cache_state,
                    credits=0,
                    attempt=attempt,
                    error=type(exc).__name__,
                )
                if attempt == attempts:
                    raise ProviderError(
                        f"FinancialFilings unreachable for GET {path}: {type(exc).__name__}"
                    ) from exc
                self._sleep(self._backoff(attempt, None))
                continue

            latency_ms = int((time.perf_counter() - started) * 1000)
            self.network_calls += 1
            status = response.status_code
            charged = _int_header(response.headers, "x-credits-charged")
            retryable = status == 429 or status >= 500
            credits = (
                charged
                if charged is not None
                else (0 if retryable or status >= 400 else estimate_credits(path))
            )
            self.credits_used += credits
            self.log.write(
                endpoint=path,
                params=log_params,
                status=status,
                cache=cache_state,
                credits=credits,
                credits_source="header" if charged is not None else "estimate",
                attempt=attempt,
                latency_ms=latency_ms,
            )

            if status < 400:
                return FRResponse(
                    status=status,
                    body=response.text,
                    total_chars=_int_header(response.headers, "x-total-chars"),
                    next_offset=_int_header(response.headers, "x-next-offset"),
                    credits=credits,
                    fetched_at=datetime.now(UTC).isoformat(),
                )
            if retryable and attempt < attempts:
                self._sleep(self._backoff(attempt, _retry_after_seconds(response.headers)))
                continue
            detail = _error_detail(response)
            if status == 404:
                raise ProviderNotFound(f"FinancialFilings: not found: GET {path} ({detail})", status)
            if retryable:
                raise ProviderError(
                    f"FinancialFilings GET {path} failed after {attempt} attempts: {status} {detail}", status
                )
            raise ProviderError(f"FinancialFilings GET {path} failed: {status} {detail}", status)
        raise AssertionError("unreachable")  # pragma: no cover

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        base = self.settings.fr_backoff_base_s * (2 ** (attempt - 1))
        delay = min(base, self.settings.fr_backoff_max_s)
        if retry_after is not None:
            delay = max(delay, retry_after)  # never retry sooner than the provider asked
        return delay

    # -- endpoints

    def search_companies(self, q: str, *, country: str | None = None) -> list[CompanyMatch]:
        data = self.request(
            "/companies/",
            {"search": q, "countries": country or self.settings.fr_country, "view": "full", "page_size": 25},
        ).json_body()
        return [CompanyMatch.model_validate(row) for row in data.get("results", [])]

    def list_filings(self, company_id: int, *, filing_type: str = "10-K") -> list[Filing]:
        filings: list[Filing] = []
        page = 1
        while True:
            data = self.request(
                "/filings/",
                {
                    "company": company_id,
                    "type": filing_type,
                    "ordering": "-release_datetime",
                    "view": "full",
                    "page_size": 100,
                    "page": page,
                },
            ).json_body()
            filings.extend(Filing.model_validate(row) for row in data.get("results", []))
            if not data.get("next"):
                return filings
            page += 1

    def get_markdown(self, filing_id: int) -> str:
        """Full report Markdown in as few billed calls as possible, length-verified."""
        path = f"/filings/{filing_id}/markdown/"
        page_chars = self.settings.fr_markdown_page_chars
        first = self.request(path, {})
        if first.total_chars is None:
            raise TruncatedContent(
                f"filing {filing_id}: response has no X-Total-Chars header; cannot verify completeness"
            )
        parts = [first.body]
        keys = [self.cache_key(path, {})]
        offset = first.next_offset
        while offset is not None:
            params = {"offset": offset, "limit": page_chars}
            page = self.request(path, params)
            keys.append(self.cache_key(path, params))
            parts.append(page.body)
            if page.next_offset is not None and page.next_offset <= offset:
                break  # provider not advancing; caught by the length check below
            offset = page.next_offset
        text = "".join(parts)
        if len(text) != first.total_chars:
            for key in keys:  # never keep a partial document as if it were complete
                self.cache.delete(key)
            raise TruncatedContent(
                f"filing {filing_id}: assembled {len(text)} chars but X-Total-Chars is {first.total_chars}; nothing saved"
            )
        return text

    def get_financials(self, company_id: int, *, revisions: bool = False) -> dict[str, Any]:
        params: dict[str, Any] = {"fiscal_period": "FY"}
        if revisions:
            params["include"] = "revisions"
        return self.request(f"/companies/{company_id}/financials/", params).json_body()

    def usage(self) -> dict[str, Any]:
        """Current provider usage. Free; live mode always asks the provider (and caches the
        answer), cached mode returns the last answer seen."""
        return self.request("/usage/", {}, refresh=self.mode == "live").json_body()


# ---------------------------------------------------------------- raw report storage


def save_report(
    settings: Settings,
    ticker: str,
    fiscal_year: int,
    filing: Filing,
    text: str,
    *,
    store: Store | None = None,
) -> ReportMeta:
    meta = ReportMeta(
        ticker=ticker.upper(),
        fiscal_year=fiscal_year,
        filing_id=filing.id,
        title=filing.title,
        document_url=filing.url,
        release_datetime=filing.release_datetime,
        total_chars=len(text),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        fetched_at=datetime.now(UTC).isoformat(),
    )
    target = store if store is not None else get_store(settings)
    try:
        target.save_report(ticker.upper(), fiscal_year, meta, text)
    finally:
        if store is None:
            target.close()
    return meta


def load_report(
    settings: Settings, ticker: str, fiscal_year: int, *, store: Store | None = None
) -> tuple[str, ReportMeta] | None:
    target = store if store is not None else get_store(settings)
    try:
        return target.load_report(ticker.upper(), fiscal_year)
    finally:
        if store is None:
            target.close()
