"""OSINT web_search tool: request shape, block-list filtering, limit and usage log (osint-research spec)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx2
from openai import AsyncOpenAI

from stock_analyzer.osint.blocklist import load_blocklist
from stock_analyzer.osint.models import RunState
from stock_analyzer.osint.search import FakeSearch, OpenRouterSearch, run_search
from stock_analyzer.store import StoreLog, get_store


class OpenRouterMock:
    """A real async openai client whose transport answers with one response and records requests.

    openai 3 sends requests through httpx2, which respx cannot intercept, so the search gets an
    injected client (as in test_llm.py). The real client still serializes the request.
    """

    def __init__(self, response: httpx2.Response):
        self._response = response
        self.requests: list[httpx2.Request] = []

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._response

    def search(self, settings) -> OpenRouterSearch:
        client = AsyncOpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key.get_secret_value(),
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle)),
        )
        return OpenRouterSearch(settings, client=client)

    @property
    def call_count(self) -> int:
        return len(self.requests)


def cited(*urls: str, cost: float = 0.0071) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "gen-1",
            "object": "chat.completion",
            "created": 0,
            "model": "anthropic/claude-haiku-5.5",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Found these results.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url_citation": {
                                    "url": u,
                                    "title": f"title {i}",
                                    "content": f"excerpt {i}",
                                    "start_index": 0,
                                    "end_index": 1,
                                },
                            }
                            for i, u in enumerate(urls)
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70, "cost": cost},
        },
    )


def make_state(max_searches: int = 3) -> RunState:
    return RunState(
        ticker="ELAL",
        company_names=["אל על", "El Al Israel Airlines"],
        window_start=date(2025, 11, 26),
        blocklist=load_blocklist("ELAL"),
        max_searches=max_searches,
        results_per_search=5,
    )


def log_records(settings):
    path = settings.logs_dir / "llm.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_request_uses_exa_with_blocklist_and_drops_blocked_results(settings):
    route = OpenRouterMock(
        cited(
            "https://www.globes.co.il/news/a",
            "https://maya.tase.co.il/reports/1",  # filing site: must never reach the agent
            "https://mayafiles.tase.co.il/rpdf/1.pdf",  # filing PDF host: blocked
            "https://www.globes.co.il/news/a/",  # duplicate of the first
        )
    )
    state = make_state()
    out = asyncio.run(run_search(state, route.search(settings), None, "El Al bonds yield"))

    assert str(route.requests[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    body = json.loads(route.requests[0].content)
    assert body["model"] == settings.model_cheap
    plugin = body["plugins"][0]
    assert plugin["id"] == "web" and plugin["engine"] == "exa" and plugin["max_results"] == 5
    assert "maya.tase.co.il" in plugin["exclude_domains"] and "magna.isa.gov.il" in plugin["exclude_domains"]
    assert ":online" not in body["model"]

    assert [r["url"] for r in out["results"]] == ["https://www.globes.co.il/news/a"]
    assert out["blocked_results"] == 2
    assert list(state.seen_urls) == ["https://www.globes.co.il/news/a"]
    assert state.searches_used == 1 and out["searches_left"] == 2
    assert abs(state.cost_usd - 0.0071) < 1e-9


def test_limit_refuses_without_provider_call(settings):
    route = OpenRouterMock(cited("https://www.globes.co.il/news/a"))
    state = make_state(max_searches=1)
    asyncio.run(run_search(state, route.search(settings), None, "first"))
    out = asyncio.run(run_search(state, route.search(settings), None, "second"))
    assert "search limit reached" in out["error"]
    assert route.call_count == 1 and state.searches_used == 1


def test_provider_error_is_readable_and_logged(settings):
    route = OpenRouterMock(httpx2.Response(500, json={"error": {"message": "boom"}}))
    log = StoreLog(get_store(settings), "llm")
    state = make_state()
    out = asyncio.run(run_search(state, route.search(settings), log, "q"))
    assert route.call_count == 1
    assert out["error"].startswith("search failed")
    rec = log_records(settings)[-1]
    assert rec["purpose"] == "osint-search" and rec["ok"] is False


def test_search_usage_logged_with_cost(settings):
    route = OpenRouterMock(cited("https://www.calcalist.co.il/a", cost=0.0075))
    log = StoreLog(get_store(settings), "llm")
    asyncio.run(run_search(make_state(), route.search(settings), log, "El Al strike"))
    rec = log_records(settings)[-1]
    assert rec["purpose"] == "osint-search" and rec["ok"] is True
    assert rec["cost"] == 0.0075 and rec["input_tokens"] == 50 and rec["output_tokens"] == 20
    assert "El Al strike" not in json.dumps(rec)  # queries are not logged


def test_fake_search_is_offline_and_records_calls():
    fake = FakeSearch()
    state = make_state()
    out = asyncio.run(run_search(state, fake, None, "El Al fleet"))
    assert len(out["results"]) == 3
    assert fake.calls[0]["exclude_domains"] == state.blocklist.exclude_domains
