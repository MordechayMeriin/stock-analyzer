"""Agent models under the LLM gateway's rules (design D8, llm-gateway spec "Agent model calls").

The OpenAI Agents SDK talks to a model through its ``Model`` interface. :class:`GatewayModel`
implements that interface around the SDK's own chat-completions model (pointed at OpenRouter)
and adds what every LLM call in this project gets:

- the model id comes from a configured *role* (``main`` / ``cheap``)
- each model turn is cached in the state store's ``llm`` namespace, keyed by everything that
  can change the answer, so an identical rerun replays the whole agent loop at zero cost
- each turn appends a usage record (tokens, cost, latency, cache hit or miss) with a purpose
  label naming the agent

The SDK's ``Usage`` has no cost field. OpenRouter's cost arrives in ``ModelResponse.raw_usage``
because the gateway sets ``preserve_raw_usage`` and asks OpenRouter to include usage.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import time
from collections.abc import Sequence
from typing import Any

from agents import Agent, ModelSettings, Runner, set_tracing_disabled
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError
from agents.items import ModelResponse
from agents.models.interface import Model, ModelTracing
from agents.usage import Usage as AgentUsage
from pydantic import BaseModel, TypeAdapter

from stock_analyzer.config import MissingCredential, Settings
from stock_analyzer.errors import StorageUnavailable
from stock_analyzer.llm import LLMError, Role
from stock_analyzer.store import Store, StoreLog, get_store

# Agent runs send nothing anywhere except the configured LLM provider (llm-gateway spec). The SDK
# traces to OpenAI by default; the usage log in the state store replaces it.
set_tracing_disabled(True)

RESPONSE_ADAPTER: TypeAdapter[ModelResponse] = TypeAdapter(ModelResponse)
STREAM_UNSUPPORTED = "agent runs use Runner.run; streamed agent turns are not supported (design D8)"


def dump_response(response: ModelResponse) -> str:
    """JSON for the cache. ``by_alias`` matters: fields such as ``async_`` only load back by alias."""
    return json.dumps(RESPONSE_ADAPTER.dump_python(response, mode="json", by_alias=True), ensure_ascii=False)


def load_response(raw: str) -> ModelResponse:
    return RESPONSE_ADAPTER.validate_python(json.loads(raw))


def usable_final(response: ModelResponse, output_schema: Any) -> bool:
    """False for a final answer that does not parse against the agent's output schema (for
    example JSON cut off at the token limit). Such a response is returned, so the run fails as it
    should, but never cached: a rerun must ask the model again, not replay the failure."""
    if output_schema is None or output_schema.is_plain_text():
        return True
    if any(getattr(item, "type", None) == "function_call" for item in response.output):
        return True  # a tool-calling turn, not a final answer
    texts = [
        part.text
        for item in response.output
        if getattr(item, "type", None) == "message"
        for part in getattr(item, "content", [])
        if getattr(part, "type", None) == "output_text"
    ]
    if not texts:
        return True
    try:
        output_schema.validate_json(texts[-1])
    except Exception:
        return False
    return True


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json", by_alias=True)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj) if not f.name.startswith("_")}
    return str(obj)


def _tool_spec(tool: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {"type": type(tool).__name__, "name": getattr(tool, "name", None)}
    for attr in ("description", "params_json_schema", "strict_json_schema"):
        if hasattr(tool, attr):
            spec[attr] = getattr(tool, attr)
    return spec


def _output_spec(output_schema: Any) -> dict[str, Any] | None:
    if output_schema is None:
        return None
    if output_schema.is_plain_text():
        return {"plain_text": True}
    return {
        "name": output_schema.name(),
        "schema": output_schema.json_schema(),
        "strict": output_schema.is_strict_json_schema(),
    }


def turn_cache_key(
    model: str,
    system_instructions: str | None,
    input: Any,
    model_settings: ModelSettings,
    tools: Sequence[Any],
    output_schema: Any,
    handoffs: Sequence[Any],
) -> str:
    payload = json.dumps(
        {
            "kind": "agent-turn",
            "model": model,
            "system": system_instructions,
            "input": input,
            "settings": model_settings.to_json_dict(),
            "tools": [_tool_spec(t) for t in tools],
            "output": _output_spec(output_schema),
            "handoffs": [getattr(h, "tool_name", str(h)) for h in handoffs],
        },
        sort_keys=True,
        ensure_ascii=False,
        default=_jsonable,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class GatewayModel(Model):
    """An Agents SDK model whose every turn goes through the gateway's cache and usage log.

    ``inner`` is the model that actually calls the provider. It defaults to the SDK's
    chat-completions model on OpenRouter, built on the first cache miss, so cache hits and
    construction never need a key. Tests inject ``inner`` (or ``client``) to stay offline.
    """

    def __init__(
        self,
        settings: Settings,
        role: Role,
        *,
        purpose: str,
        store: Store | None = None,
        client: Any | None = None,
        inner: Model | None = None,
    ):
        self.settings = settings
        self.role = role
        self.model = settings.model_for(role)
        self.purpose = purpose
        self.store: Store = store if store is not None else get_store(settings)
        self.log = StoreLog(self.store, "llm")
        self._client = client
        self._inner = inner

    @property
    def inner(self) -> Model:
        if self._inner is None:
            from agents import OpenAIChatCompletionsModel
            from openai import AsyncOpenAI

            client = self._client
            if client is None:
                if self.settings.openrouter_api_key is None:
                    raise MissingCredential("OPENROUTER_API_KEY", "A live agent call")
                client = AsyncOpenAI(
                    base_url=self.settings.openrouter_base_url,
                    api_key=self.settings.openrouter_api_key.get_secret_value(),
                    timeout=self.settings.llm_timeout_s,
                    max_retries=2,
                )
            self._inner = OpenAIChatCompletionsModel(model=self.model, openai_client=client)
        return self._inner

    def gateway_settings(self, model_settings: ModelSettings) -> ModelSettings:
        """Gateway defaults, overlaid by the agent's own settings, with usage reporting forced on."""
        base = ModelSettings(temperature=0, max_tokens=self.settings.agent_max_output_tokens)
        merged = base.resolve(model_settings)
        extra_body = {**(merged.extra_body or {}), "usage": {"include": True}}
        return merged.resolve(
            ModelSettings(preserve_raw_usage=True, include_usage=True, extra_body=extra_body)
        )

    async def get_response(
        self,
        system_instructions: str | None,
        input: Any,
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any | None = None,
    ) -> ModelResponse:
        settings = self.gateway_settings(model_settings)
        key = turn_cache_key(self.model, system_instructions, input, settings, tools, output_schema, handoffs)
        cache = self.store.cache("llm")

        try:
            cached = await asyncio.to_thread(cache.get, key)
        except StorageUnavailable:
            cached = None  # the cache is an optimization: a store hiccup is a miss, not a failed turn
        if cached is not None:
            await asyncio.to_thread(self._write, 0, 0, 0.0, 0, True, True, None)
            hit = load_response(cached)
            # served from the cache at zero cost: report no usage, so run totals count only paid turns
            return ModelResponse(
                output=hit.output,
                usage=AgentUsage(requests=1),
                response_id=hit.response_id,
                raw_usage={"cost": 0.0},
            )

        started = time.perf_counter()
        try:
            response = await self.inner.get_response(
                system_instructions,
                input,
                settings,
                tools,
                output_schema,
                handoffs,
                tracing,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                prompt=prompt,
            )
        except MissingCredential:
            raise
        except Exception as exc:  # transport / API error
            latency = int((time.perf_counter() - started) * 1000)
            await asyncio.to_thread(self._write, 0, 0, None, latency, False, False, repr(exc)[:500])
            raise LLMError(f"agent model call failed ({self.purpose}): {exc}") from exc

        latency = int((time.perf_counter() - started) * 1000)
        raw = response.raw_usage or {}
        cost = raw.get("cost")
        if usable_final(response, output_schema):
            try:
                await asyncio.to_thread(cache.set, key, dump_response(response))
            except StorageUnavailable:
                pass  # not cached this time; the paid answer is still returned (and logged below)
        await asyncio.to_thread(
            self._write,
            response.usage.input_tokens,
            response.usage.output_tokens,
            float(cost) if cost is not None else None,
            latency,
            False,
            True,
            None,
        )
        return response

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(STREAM_UNSUPPORTED)

    def _write(
        self,
        input_tokens: int,
        output_tokens: int,
        cost: float | None,
        latency_ms: int,
        cache_hit: bool,
        ok: bool,
        error: str | None,
    ) -> None:
        record: dict[str, Any] = {
            "model": self.model,
            "purpose": self.purpose,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "latency_ms": latency_ms,
            "cache_hit": cache_hit,
            "ok": ok,
            "attempts": 0 if cache_hit else 1,
            "agent": True,
        }
        if error is not None:
            record["error"] = error
        self.log.write(**record)


# ---------------------------------------------------------------- fake


@dataclasses.dataclass(frozen=True)
class ToolCall:
    """A scripted model turn that calls a tool. Build it with :func:`tool_call`."""

    name: str
    arguments: dict[str, Any]


def tool_call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(name, arguments)


@dataclasses.dataclass
class FakeTurn:
    """What the fake model was asked on one turn (for test assertions)."""

    purpose: str
    model: str
    system: str | None
    input: Any
    tools: list[str]
    output_schema: dict[str, Any] | None

    def tool_outputs(self) -> list[str]:
        """The tool results the runner sent back on this turn, oldest first."""
        items = self.input if isinstance(self.input, list) else []
        return [
            str(item.get("output"))
            for item in items
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]


FakeEntry = ToolCall | str | dict[str, Any] | BaseModel | Any


class FakeAgentModel(Model):
    """Offline agent model: scripted turns, no network, no key, zero cost (llm-gateway spec).

    ``script`` is a list consumed one entry per model turn. An entry is a :class:`ToolCall`
    (the runner executes the real tool), a final output (JSON text, a dict or a model
    instance), or a callable that takes the :class:`FakeTurn` and returns one of those, for
    outputs that depend on earlier tool results. With no script left, the final output is a
    minimal object derived from the agent's output schema.
    """

    def __init__(
        self,
        settings: Settings | None,
        role: Role,
        *,
        purpose: str,
        script: list[FakeEntry] | None = None,
        store: Store | None = None,
        turns: list[FakeTurn] | None = None,
    ):
        self.model = f"fake/{settings.model_for(role) if settings else role}"
        self.purpose = purpose
        self.script = script if script is not None else []
        if store is None and settings is not None:
            store = get_store(settings)
        self.log = StoreLog(store, "llm") if store is not None else None
        self.turns = turns if turns is not None else []

    async def get_response(
        self,
        system_instructions: str | None,
        input: Any,
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any | None = None,
    ) -> ModelResponse:
        from agents.usage import Usage as AgentUsage

        turn = FakeTurn(
            purpose=self.purpose,
            model=self.model,
            system=system_instructions,
            input=input,
            tools=[getattr(t, "name", type(t).__name__) for t in tools],
            output_schema=_output_spec(output_schema),
        )
        self.turns.append(turn)
        entry: Any = self.script.pop(0) if self.script else None
        if callable(entry) and not isinstance(entry, (BaseModel, ToolCall)):
            entry = entry(turn)
        output = [self._item(entry, output_schema, len(self.turns))]
        in_tokens = len(json.dumps(input, ensure_ascii=False, default=_jsonable)) // 4
        out_tokens = max(len(json.dumps(_jsonable(output[0]), ensure_ascii=False)) // 4, 1)
        if self.log is not None:
            self.log.write(
                model=self.model,
                purpose=self.purpose,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cost=0.0,
                latency_ms=0,
                cache_hit=False,
                ok=True,
                attempts=1,
                agent=True,
                fake=True,
            )
        usage = AgentUsage(requests=1, input_tokens=in_tokens, output_tokens=out_tokens)
        return ModelResponse(output=output, usage=usage, response_id=None, raw_usage={"cost": 0.0})

    def _item(self, entry: Any, output_schema: Any, n: int) -> Any:
        from openai.types.responses import (
            ResponseFunctionToolCall,
            ResponseOutputMessage,
            ResponseOutputText,
        )

        if isinstance(entry, ToolCall):
            return ResponseFunctionToolCall(
                type="function_call",
                call_id=f"call_{n}",
                id=f"fc_{n}",
                name=entry.name,
                arguments=json.dumps(entry.arguments, ensure_ascii=False, default=_jsonable),
            )
        if entry is None:
            if output_schema is None or output_schema.is_plain_text():
                text = "תשובה לדוגמה מהמודל המדומה."
            else:
                from stock_analyzer.llm import example_from_schema

                text = json.dumps(example_from_schema(output_schema.json_schema()), ensure_ascii=False)
        elif isinstance(entry, BaseModel):
            text = entry.model_dump_json()
        elif isinstance(entry, str):
            text = entry
        else:
            text = json.dumps(entry, ensure_ascii=False, default=_jsonable)
        return ResponseOutputMessage(
            type="message",
            id=f"msg_{n}",
            role="assistant",
            status="completed",
            content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
        )

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(STREAM_UNSUPPORTED)


@dataclasses.dataclass
class FakeAgentModels:
    """A model factory for pipelines under test: one :class:`FakeAgentModel` per purpose.

    ``script`` maps an agent purpose to its list of turns (see :class:`FakeAgentModel`); a
    ``"*"`` entry is the fallback. Every turn of every agent is recorded in ``turns``.
    """

    settings: Settings | None = None
    store: Store | None = None
    script: dict[str, list[FakeEntry]] = dataclasses.field(default_factory=dict)
    turns: list[FakeTurn] = dataclasses.field(default_factory=list)

    def __call__(self, role: Role, purpose: str) -> FakeAgentModel:
        # a purpose without its own script shares (and consumes) the "*" fallback list
        script = self.script[purpose] if purpose in self.script else self.script.setdefault("*", [])
        return FakeAgentModel(
            self.settings, role, purpose=purpose, script=script, store=self.store, turns=self.turns
        )


def agent_model_factory(settings: Settings, store: Store | None = None):
    """The configured agent model factory ``(role, purpose) -> Model``.

    ``LLM_FAKE`` gives offline fakes; otherwise every agent gets a :class:`GatewayModel`.
    """
    if settings.llm_fake:
        return FakeAgentModels(settings=settings, store=store)

    def make(role: Role, purpose: str) -> Model:
        return GatewayModel(settings, role, purpose=purpose, store=store)

    return make


# ---------------------------------------------------------------- running


class AgentTurnLimit(LLMError):
    """An agent used up its model turns without producing a final output."""

    def __init__(self, agent: str, limit: int):
        self.agent = agent
        self.limit = limit
        super().__init__(f"agent {agent!r} reached its limit of {limit} model turns without a final answer")


@dataclasses.dataclass
class UsageTotals:
    """Tokens and cost summed over the model turns of one or more agent runs."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    turns: int = 0

    def add(self, response: ModelResponse) -> None:
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        cost = (response.raw_usage or {}).get("cost")
        self.cost += float(cost) if cost is not None else 0.0
        self.turns += 1


async def run_agent(
    agent: Agent[Any],
    input: Any,
    *,
    max_turns: int,
    context: Any | None = None,
    usage: UsageTotals | None = None,
) -> Any:
    """Run one agent to its final output, with the configured turn limit (llm-gateway spec)."""
    for attempt in (1, 2):
        try:
            result = await Runner.run(agent, input, context=context, max_turns=max_turns)
            break
        except MaxTurnsExceeded as exc:
            raise AgentTurnLimit(agent.name, max_turns) from exc
        except ModelBehaviorError:
            # invalid structured output (e.g. malformed JSON): one fresh attempt, as the gateway's
            # single repair retry; the bad answer was not cached, so this asks the model again
            if attempt == 2:
                raise
    if usage is not None:
        for response in result.raw_responses:
            usage.add(response)
    return result.final_output
