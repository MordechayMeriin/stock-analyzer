"""The ``web_search`` tool behind the OSINT agents (design D2-D3).

One search = one OpenRouter call on the cheap model with the web plugin forced to the Exa engine, because
OpenAI's native search ignores ``exclude_domains``. The tool enforces the per-run search limit, drops every
blocked URL in code, records the URLs it returned (so findings can be checked against them) and logs usage.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from stock_analyzer.config import MissingCredential, Settings
from stock_analyzer.osint.models import RunState, SearchHit, normalize_url
from stock_analyzer.store import StoreLog

SEARCH_PURPOSE = "osint-search"
SNIPPET_CHARS = 3000  # the claim check (improve-osint-evidence D3) reads these excerpts
SUMMARY_CHARS = 3000

SEARCH_SYSTEM = (
    "You are a web search assistant. Use the web search results to list every relevant result for the "
    "user's query. For each result give its title, its publish date when visible, and one or two sentences "
    "on what it says. Do not add facts that are not in the results."
)


@dataclass
class SearchResponse:
    hits: list[SearchHit]
    summary: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None


class SearchBackend(Protocol):
    async def search(self, query: str, max_results: int, exclude_domains: list[str]) -> SearchResponse: ...


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(vars(obj))


def parse_citations(message: Any) -> list[SearchHit]:
    """``url_citation`` annotations of a chat completion message, de-duplicated by URL."""
    hits: dict[str, SearchHit] = {}
    for ann in _as_dict(message).get("annotations") or []:
        ann = _as_dict(ann)
        if ann.get("type") != "url_citation":
            continue
        cite = _as_dict(ann.get("url_citation"))
        url = str(cite.get("url") or "").strip()
        if not url:
            continue
        key = normalize_url(url)
        if key not in hits:
            hits[key] = SearchHit(
                url=url,
                title=str(cite.get("title") or ""),
                snippet=str(cite.get("content") or "")[:SNIPPET_CHARS],
            )
    return list(hits.values())


class OpenRouterSearch:
    """Live search through OpenRouter's web plugin (Exa engine)."""

    def __init__(self, settings: Settings, *, client: Any | None = None):
        self.settings = settings
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            if self.settings.openrouter_api_key is None:
                raise MissingCredential("OPENROUTER_API_KEY", "OSINT web search")
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                base_url=self.settings.openrouter_base_url,
                api_key=self.settings.openrouter_api_key.get_secret_value(),
                timeout=self.settings.llm_timeout_s,
                max_retries=2,
            )
        return self._client

    async def search(self, query: str, max_results: int, exclude_domains: list[str]) -> SearchResponse:
        model = self.settings.model_for("cheap")
        plugin: dict[str, Any] = {"id": "web", "engine": "exa", "max_results": max_results}
        if exclude_domains:
            plugin["exclude_domains"] = list(exclude_domains)
        response = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SEARCH_SYSTEM}, {"role": "user", "content": query}],
            max_tokens=1500,
            temperature=0,
            extra_body={"plugins": [plugin], "usage": {"include": True}},
        )
        message = response.choices[0].message if response.choices else None
        usage = _as_dict(getattr(response, "usage", None))
        cost = usage.get("cost")
        return SearchResponse(
            hits=parse_citations(message),
            summary=str(getattr(message, "content", "") or "")[:SUMMARY_CHARS],
            model=model,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cost=float(cost) if cost is not None else None,
        )


@dataclass
class FakeSearch:
    """Offline search for LLM_FAKE and tests: scripted hits per query, or generated ones."""

    script: dict[str, list[SearchHit]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def search(self, query: str, max_results: int, exclude_domains: list[str]) -> SearchResponse:
        self.calls.append(
            {"query": query, "max_results": max_results, "exclude_domains": list(exclude_domains)}
        )
        hits = self.script.get(query)
        if hits is None:
            slug = hashlib.sha1(query.encode("utf-8")).hexdigest()[:10]
            hits = [
                SearchHit(
                    url=f"https://news.example.com/osint/{slug}-{n}",
                    title=f"Example result {n} for: {query}",
                    snippet=f"Published 2026-10-0{n}. Example coverage related to {query}.",
                )
                for n in range(1, min(max_results, 3) + 1)
            ]
        return SearchResponse(
            hits=list(hits)[:max_results], summary=f"Example results for {query}.", model="fake/search"
        )


async def run_search(
    state: RunState, backend: SearchBackend, log: StoreLog | None, query: str
) -> dict[str, Any]:
    """Execute one ``web_search`` tool call. Errors come back as ``{"error": ...}`` for the agent to read."""
    query = query.strip()
    if not query:
        return {"error": "empty query"}
    if state.searches_used >= state.max_searches:
        return {
            "error": f"search limit reached ({state.max_searches} searches in this run); "
            "report the findings you already have"
        }
    state.searches_used += 1
    state.progress("search", query=query)
    started = time.perf_counter()
    try:
        response = await backend.search(query, state.results_per_search, state.blocklist.exclude_domains)
    except MissingCredential:
        raise
    except Exception as exc:  # provider or transport error: tell the agent, keep the run going
        if log is not None:
            log.write(
                model=getattr(getattr(backend, "settings", None), "model_cheap", "unknown"),
                purpose=SEARCH_PURPOSE,
                input_tokens=0,
                output_tokens=0,
                cost=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                cache_hit=False,
                ok=False,
                attempts=1,
                error=repr(exc)[:500],
            )
        return {
            "error": f"search failed: {exc}"[:300],
            "searches_left": state.max_searches - state.searches_used,
        }

    state.add_cost(response.cost)
    if log is not None:
        log.write(
            model=response.model,
            purpose=SEARCH_PURPOSE,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost=response.cost,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cache_hit=False,
            ok=True,
            attempts=1,
        )

    results = []
    blocked = 0
    for hit in response.hits:
        if state.blocklist.blocks(hit.url):
            blocked += 1
            continue
        state.seen_urls.setdefault(normalize_url(hit.url), hit)
        results.append({"url": hit.url, "title": hit.title, "snippet": hit.snippet})
    return {
        "query": query,
        "results": results,
        "summary": response.summary,
        "blocked_results": blocked,
        "searches_left": state.max_searches - state.searches_used,
    }
