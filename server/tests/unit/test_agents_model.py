"""GatewayModel: agent turns through the gateway's cache and usage log (llm-gateway spec)."""

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest
from agents import Agent, Runner, function_tool
from openai import AsyncOpenAI
from pydantic import BaseModel

from stock_analyzer.agents_model import (
    AgentTurnLimit,
    FakeAgentModel,
    FakeAgentModels,
    GatewayModel,
    agent_model_factory,
    run_agent,
    tool_call,
)
from stock_analyzer.config import MissingCredential, Settings
from stock_analyzer.llm import LLMError, read_llm_totals


class Verdict(BaseModel):
    verdict: str


def chat_completion(message: dict, cost: float = 0.0012, prompt: int = 100, out: int = 20) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "gen-1",
            "object": "chat.completion",
            "created": 0,
            "model": "anthropic/claude-sonnet-5.5",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}],
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": out,
                "total_tokens": prompt + out,
                "cost": cost,
            },
        },
    )


class OpenRouterMock:
    def __init__(self, responses: list[httpx2.Response]):
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected provider call")
        return self.responses.pop(0)

    def client(self, settings: Settings) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key.get_secret_value(),
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle)),
        )

    def body(self, i: int) -> dict:
        return json.loads(self.requests[i].content)


def log_records(settings: Settings) -> list[dict]:
    path = settings.logs_dir / "llm.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run(agent: Agent, text: str = "go"):
    return asyncio.run(Runner.run(agent, text, max_turns=4))


def verdict_agent(model: GatewayModel) -> Agent:
    return Agent(name="judge", instructions="Answer in JSON.", model=model, output_type=Verdict)


def test_miss_calls_provider_logs_cost_and_caches(settings):
    mock = OpenRouterMock([chat_completion({"content": '{"verdict": "BUY"}'})])
    model = GatewayModel(settings, "main", purpose="story.test", client=mock.client(settings))

    result = run(verdict_agent(model))

    assert result.final_output == Verdict(verdict="BUY")
    body = mock.body(0)
    assert body["model"] == settings.model_main
    assert body["usage"] == {"include": True}  # OpenRouter reports cost only when asked
    assert body["temperature"] == 0
    (rec,) = log_records(settings)
    assert rec["purpose"] == "story.test" and rec["agent"] is True
    assert rec["cache_hit"] is False and rec["ok"] is True
    assert rec["input_tokens"] == 100 and rec["output_tokens"] == 20
    assert rec["cost"] == 0.0012  # from ModelResponse.raw_usage
    assert "DO-NOT-LOG" not in (settings.logs_dir / "llm.jsonl").read_text(encoding="utf-8")


def test_identical_rerun_is_served_from_cache(settings):
    first = OpenRouterMock([chat_completion({"content": '{"verdict": "HOLD"}'})])
    a = run(
        verdict_agent(GatewayModel(settings, "main", purpose="story.test", client=first.client(settings)))
    )

    nothing = OpenRouterMock([])  # any provider call fails the test
    b = run(
        verdict_agent(GatewayModel(settings, "main", purpose="story.test", client=nothing.client(settings)))
    )

    assert a.final_output == b.final_output == Verdict(verdict="HOLD")
    assert nothing.requests == []
    miss, hit = log_records(settings)
    assert miss["cache_hit"] is False and miss["cost"] > 0
    assert hit["cache_hit"] is True and hit["cost"] == 0
    totals = read_llm_totals(settings.logs_dir / "llm.jsonl")
    assert totals["calls"] == 2 and totals["cache_hits"] == 1


def test_different_instructions_are_a_different_turn(settings):
    mock = OpenRouterMock(
        [chat_completion({"content": '{"verdict": "A"}'}), chat_completion({"content": '{"verdict": "B"}'})]
    )
    model = GatewayModel(settings, "main", purpose="story.test", client=mock.client(settings))
    run(verdict_agent(model))
    other = Agent(name="judge", instructions="Answer differently.", model=model, output_type=Verdict)
    assert run(other).final_output == Verdict(verdict="B")
    assert len(mock.requests) == 2


def test_tool_loop_through_the_gateway(settings):
    calls: list[int] = []

    @function_tool
    def double(n: int) -> str:
        """Double a number."""
        calls.append(n)
        return str(n * 2)

    tool_call = {
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "double", "arguments": '{"n": 21}'}}
        ],
    }
    mock = OpenRouterMock(
        [
            chat_completion(tool_call, cost=0.001),
            chat_completion({"content": '{"verdict": "42"}'}, cost=0.002),
        ]
    )
    model = GatewayModel(settings, "cheap", purpose="story.tool", client=mock.client(settings))
    agent = Agent(
        name="doubler", instructions="Use the tool.", model=model, tools=[double], output_type=Verdict
    )

    assert run(agent).final_output == Verdict(verdict="42")
    assert calls == [21]
    assert mock.body(0)["model"] == settings.model_cheap
    assert mock.body(0)["tools"][0]["function"]["name"] == "double"
    tool_result = [m for m in mock.body(1)["messages"] if m["role"] == "tool"]
    assert tool_result and tool_result[0]["content"] == "42"
    assert [r["cost"] for r in log_records(settings)] == [0.001, 0.002]


def test_missing_key_names_the_variable(tmp_path):
    s = Settings(data_dir=tmp_path)
    with pytest.raises(MissingCredential, match="OPENROUTER_API_KEY"):
        run(verdict_agent(GatewayModel(s, "main", purpose="story.test")))


def test_provider_error_is_logged_and_raised(settings):
    mock = OpenRouterMock([httpx2.Response(500, json={"error": {"message": "boom"}})])
    model = GatewayModel(settings, "main", purpose="story.fail", client=mock.client(settings))
    with pytest.raises(LLMError, match="story.fail"):
        run(verdict_agent(model))
    (rec,) = log_records(settings)
    assert rec["ok"] is False and rec["cache_hit"] is False and "error" in rec


def test_streaming_is_not_supported(settings):
    with pytest.raises(NotImplementedError):
        GatewayModel(settings, "main", purpose="x").stream_response()


# ---------------------------------------------------------------- FakeAgentModel


def test_fake_runs_real_tool_then_scripted_output(settings):
    seen: list[str] = []

    @function_tool
    def lookup(code: str) -> str:
        """Look up a code."""
        seen.append(code)
        return f"value-of-{code}"

    fakes = FakeAgentModels(
        settings=settings,
        script={
            "story.fake": [
                tool_call("lookup", code="revenue"),
                lambda turn: {"verdict": turn.tool_outputs()[-1]},  # output depends on the tool result
            ]
        },
    )
    agent = Agent(
        name="faker",
        instructions="x",
        model=fakes("cheap", "story.fake"),
        tools=[lookup],
        output_type=Verdict,
    )

    result = run(agent)

    assert seen == ["revenue"]
    assert result.final_output == Verdict(verdict="value-of-revenue")
    assert [t.purpose for t in fakes.turns] == ["story.fake", "story.fake"]
    assert fakes.turns[0].tools == ["lookup"]
    assert fakes.turns[0].output_schema["schema"]["required"] == ["verdict"]
    records = log_records(settings)
    assert len(records) == 2 and all(r["fake"] and r["cost"] == 0.0 for r in records)


def test_fake_unscripted_output_is_schema_derived(settings):
    agent = Agent(
        name="x", instructions="x", model=FakeAgentModels(settings=settings)("main", "p"), output_type=Verdict
    )
    assert isinstance(run(agent).final_output, Verdict)


def test_factory_follows_llm_fake(settings):
    assert isinstance(
        agent_model_factory(settings.model_copy(update={"llm_fake": True}))("main", "p"), FakeAgentModel
    )
    assert isinstance(agent_model_factory(settings)("main", "p"), GatewayModel)


# ---------------------------------------------------------------- limits and tracing


def test_endless_tool_calls_hit_the_turn_limit(settings):
    @function_tool
    def ping() -> str:
        """Ping."""
        return "pong"

    fakes = FakeAgentModels(settings=settings, script={"story.loop": [tool_call("ping") for _ in range(20)]})
    agent = Agent(
        name="looper", instructions="x", model=fakes("cheap", "story.loop"), tools=[ping], output_type=Verdict
    )

    with pytest.raises(AgentTurnLimit, match="'looper'.*3 model turns") as info:
        asyncio.run(
            run_agent(
                agent, "go", max_turns=settings.model_copy(update={"agent_max_turns": 3}).agent_max_turns
            )
        )
    assert info.value.agent == "looper" and info.value.limit == 3


def test_run_agent_returns_final_output(settings):
    fakes = FakeAgentModels(settings=settings, script={"p": [{"verdict": "ok"}]})
    agent = Agent(name="a", instructions="x", model=fakes("main", "p"), output_type=Verdict)
    assert asyncio.run(run_agent(agent, "go", max_turns=settings.agent_max_turns)) == Verdict(verdict="ok")


def test_tracing_is_disabled_after_importing_the_story_package():
    import importlib

    from agents import set_tracing_disabled
    from agents.tracing import get_trace_provider

    set_tracing_disabled(False)
    import stock_analyzer.agents_model as module

    importlib.reload(module)  # the module-level switch runs on import
    import stock_analyzer.story  # noqa: F401

    assert get_trace_provider().is_disabled() is True


# ---------------------------------------------------------------- invalid output (live-run findings)


def test_truncated_answer_is_not_cached_and_retried_once(settings):
    truncated = chat_completion({"content": '{"verdict": "BU'}, out=16000)
    mock = OpenRouterMock([truncated, chat_completion({"content": '{"verdict": "BUY"}'})])
    model = GatewayModel(settings, "cheap", purpose="story.trunc", client=mock.client(settings))

    out = asyncio.run(run_agent(verdict_agent(model), "go", max_turns=4))

    assert out == Verdict(verdict="BUY")
    assert len(mock.requests) == 2  # the retry asked the model again instead of replaying the cache
    assert mock.body(0)["max_tokens"] == settings.agent_max_output_tokens
    # a rerun replays the valid answer from the cache, not the truncated one
    nothing = OpenRouterMock([])
    again = GatewayModel(settings, "cheap", purpose="story.trunc", client=nothing.client(settings))
    assert asyncio.run(run_agent(verdict_agent(again), "go", max_turns=4)) == Verdict(verdict="BUY")
    assert nothing.requests == []


def test_invalid_answer_twice_raises(settings):
    from agents.exceptions import ModelBehaviorError

    bad = [chat_completion({"content": "not json"}), chat_completion({"content": "still not json"})]
    model = GatewayModel(settings, "cheap", purpose="story.bad", client=OpenRouterMock(bad).client(settings))
    with pytest.raises(ModelBehaviorError):
        asyncio.run(run_agent(verdict_agent(model), "go", max_turns=4))


def test_cache_outage_is_a_miss_not_a_failed_turn(settings, monkeypatch):
    from stock_analyzer.errors import StorageUnavailable

    mock = OpenRouterMock([chat_completion({"content": '{"verdict": "OK"}'})])
    model = GatewayModel(settings, "cheap", purpose="story.outage", client=mock.client(settings))

    class DownCache:
        def get(self, key):
            raise StorageUnavailable("database unreachable (OperationalError)")

        def set(self, key, value):
            raise StorageUnavailable("database unreachable (OperationalError)")

    monkeypatch.setattr(model.store, "cache", lambda namespace: DownCache())
    assert run(verdict_agent(model)).final_output == Verdict(verdict="OK")
    (rec,) = log_records(settings)  # the usage log is still written
    assert rec["cache_hit"] is False and rec["cost"] == 0.0012
