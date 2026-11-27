import json
from collections.abc import Callable, Iterator

import httpx2
import pytest
from openai import OpenAI
from pydantic import BaseModel, Field

from stock_analyzer.config import MissingCredential, Settings
from stock_analyzer.llm import (
    DeltaEvent,
    DoneEvent,
    FakeLLM,
    LLMOutputError,
    OpenRouterLLM,
    example_from_schema,
    get_llm,
    read_llm_totals,
)

URL = "https://openrouter.ai/api/v1/chat/completions"


class Verdict(BaseModel):
    verdict: str
    score: int = Field(ge=1, le=5)


class OpenRouterMock:
    """A real openai client whose transport answers from a script and records every request.

    openai 3 sends requests through httpx2, which respx cannot intercept, so the gateway gets
    an injected client (design D9). The real client still serializes the request and parses
    the response, so the assertions below cover what goes over the wire.
    """

    def __init__(self, responses: list[httpx2.Response] | Callable[[], httpx2.Response]):
        self._responses = responses
        self.requests: list[httpx2.Request] = []

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if callable(self._responses):
            return self._responses()
        return self._responses.pop(0)

    def client(self, settings) -> OpenAI:
        return OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key.get_secret_value(),
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self._handle)),
        )

    def body(self, i: int) -> dict:
        return json.loads(self.requests[i].content)

    @property
    def call_count(self) -> int:
        return len(self.requests)


@pytest.fixture
def openrouter(settings) -> Iterator[Callable[..., tuple[OpenRouterLLM, OpenRouterMock]]]:
    def make(responses) -> tuple[OpenRouterLLM, OpenRouterMock]:
        mock = OpenRouterMock(responses)
        return OpenRouterLLM(settings, client=mock.client(settings)), mock

    yield make


def completion(content: str, prompt=100, completion_tokens=20, cost=0.0012) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "gen-1",
            "object": "chat.completion",
            "created": 0,
            "model": "anthropic/claude-sonnet-5.5",
            "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
            ],
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt + completion_tokens,
                "cost": cost,
            },
        },
    )


def log_records(settings):
    path = settings.logs_dir / "llm.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_valid_output(settings, openrouter):
    llm, mock = openrouter([completion('{"verdict": "BUY", "score": 4}')])
    out = llm.complete_json("main", "sys", "user", Verdict, purpose="t")
    assert out == Verdict(verdict="BUY", score=4)
    assert str(mock.requests[0].url) == URL
    body = mock.body(0)
    assert body["model"] == settings.model_main
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"]["required"] == ["verdict", "score"]
    assert body["usage"] == {"include": True}  # OpenRouter reports cost only when asked
    assert mock.requests[0].headers["authorization"] == "Bearer test-or-key-DO-NOT-LOG"
    (rec,) = log_records(settings)
    assert rec["ok"] and not rec["cache_hit"] and rec["input_tokens"] == 100 and rec["cost"] == 0.0012
    assert "DO-NOT-LOG" not in (settings.logs_dir / "llm.jsonl").read_text()


def test_successful_repair(settings, openrouter):
    llm, mock = openrouter([completion('{"verdict": "BUY"}'), completion('{"verdict": "BUY", "score": 3}')])
    out = llm.complete_json("cheap", "sys", "user", Verdict, purpose="repair")
    assert out.score == 3
    assert mock.call_count == 2
    repair = mock.body(1)
    assert repair["model"] == settings.model_cheap
    assert repair["messages"][-2] == {"role": "assistant", "content": '{"verdict": "BUY"}'}
    assert "score" in repair["messages"][-1]["content"]  # the validation error is carried
    (rec,) = log_records(settings)
    assert rec["attempts"] == 2 and rec["input_tokens"] == 200


def test_failed_repair_raises_with_raw_output(settings, openrouter):
    llm, _ = openrouter([completion("not json"), completion('{"verdict": "X", "score": 9}')])
    with pytest.raises(LLMOutputError) as info:
        llm.complete_json("main", "sys", "user", Verdict)
    assert info.value.raw_output == '{"verdict": "X", "score": 9}'
    assert "score" in str(info.value)
    (rec,) = log_records(settings)
    assert rec["ok"] is False


def test_second_identical_call_is_cache_hit(settings, openrouter):
    llm, mock = openrouter(lambda: completion('{"verdict": "HOLD", "score": 2}'))
    a = llm.complete_json("main", "sys", "user", Verdict, purpose="c")
    b = OpenRouterLLM(settings, client=mock.client(settings)).complete_json(
        "main", "sys", "user", Verdict, purpose="c"
    )  # new instance, same store
    assert a == b
    assert mock.call_count == 1
    first, second = log_records(settings)
    assert first["cache_hit"] is False and first["cost"] > 0
    assert second["cache_hit"] is True and second["cost"] == 0
    # a different prompt, schema param or model is a different key
    llm.complete_json("main", "sys", "other user", Verdict)
    llm.complete_json("main", "sys", "user", Verdict, params={"temperature": 0.5})
    assert mock.call_count == 3
    totals = read_llm_totals(settings.logs_dir / "llm.jsonl")
    assert totals["calls"] == 4 and totals["cache_hits"] == 1


def sse(chunks: list[dict]) -> httpx2.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def chunk(text=None, usage=None):
    c = {
        "id": "g",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [] if text is None else [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    if usage:
        c["usage"] = usage
    return c


def test_stream_text_yields_deltas_then_usage(settings, openrouter):
    llm, mock = openrouter(
        [
            sse(
                [
                    chunk("שלום "),
                    chunk("עולם"),
                    chunk(usage={"prompt_tokens": 50, "completion_tokens": 7, "cost": 0.0003}),
                ]
            )
        ]
    )
    events = list(llm.stream_text("main", "sys", "q", purpose="playground"))
    assert [e.text for e in events if isinstance(e, DeltaEvent)] == ["שלום ", "עולם"]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.usage.input_tokens == 50 and done.usage.output_tokens == 7 and done.usage.cost == 0.0003
    body = mock.body(0)
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    (rec,) = log_records(settings)
    assert rec["stream"] is True and rec["purpose"] == "playground"


def test_missing_key_names_the_variable(tmp_path):
    s = Settings(data_dir=tmp_path)
    with pytest.raises(MissingCredential, match="OPENROUTER_API_KEY"):
        OpenRouterLLM(s).complete_json("main", "s", "u", Verdict)


def test_model_swap_by_config(settings, tmp_path):
    swapped = settings.model_copy(update={"model_main": "vendor/new-main"})
    fake = FakeLLM(settings=swapped)
    fake.complete_json("main", "s", "u", Verdict)
    assert fake.calls[0].model == "fake/vendor/new-main"


# ---------------------------------------------------------------- FakeLLM


def test_fake_schema_derived_and_scripted(settings):
    fake = FakeLLM(
        settings=settings,
        script={"materiality": ['{"verdict": "A", "score": 5}', {"verdict": "B", "score": 1}]},
    )
    derived = fake.complete_json("main", "s", "u", Verdict, purpose="other")
    assert derived.score == 1  # minimum satisfies ge=1
    assert fake.complete_json("cheap", "s", "u", Verdict, purpose="materiality").verdict == "A"
    assert fake.complete_json("cheap", "s", "u", Verdict, purpose="materiality").verdict == "B"
    assert [c.purpose for c in fake.calls] == ["other", "materiality", "materiality"]


def test_fake_invalid_script_raises_like_real(settings):
    fake = FakeLLM(settings=settings, script={"*": '{"verdict": "A"}'})
    with pytest.raises(LLMOutputError):
        fake.complete_json("main", "s", "u", Verdict)


def test_fake_streaming(settings):
    fake = FakeLLM(settings=settings, script={"playground": "תשובה ארוכה מספיק כדי להתפצל"}, chunk_chars=5)
    events = list(fake.stream_text("main", "s", "u", purpose="playground"))
    assert "".join(e.text for e in events if isinstance(e, DeltaEvent)) == "תשובה ארוכה מספיק כדי להתפצל"
    assert len(events) > 3 and isinstance(events[-1], DoneEvent) and events[-1].usage.cost == 0.0
    assert read_llm_totals(settings.logs_dir / "llm.jsonl")["total_cost_usd"] == 0


def test_get_llm_fake_needs_no_key(tmp_path):
    s = Settings(data_dir=tmp_path, llm_fake=True)
    llm = get_llm(s)
    assert isinstance(llm, FakeLLM)
    assert llm.complete_json("main", "s", "u", Verdict).verdict


def test_example_from_schema_nested():
    class Item(BaseModel):
        ids: list[str] = Field(min_length=2)
        kind: str | None = None

    class Out(BaseModel):
        items: list[Item] = Field(min_length=1)
        flag: bool

    Out.model_validate(example_from_schema(Out.model_json_schema()))


def test_network_is_blocked():
    import socket

    with pytest.raises(Exception, match="network access attempted"):
        socket.create_connection(("1.1.1.1", 443), timeout=1)
