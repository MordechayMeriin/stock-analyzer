"""LLM gateway (plan.md §1.7, llm-gateway spec).

One entry point for every LLM call:

- :meth:`OpenRouterLLM.complete_json` sends (model, system, user, schema) through OpenRouter's
  OpenAI-compatible API with JSON-schema output, validates with pydantic, and makes exactly
  one repair request carrying the validation error. Results are cached in the state store.
- :meth:`OpenRouterLLM.stream_text` streams text increments followed by a final usage/cost event.
- Every provider call (and cache hit) appends a usage record to the state store.
- :class:`FakeLLM` has the same interface, makes no network calls, and returns scripted or
  schema-derived responses so the test suite runs offline.

Callers pick a model *role* (``main`` / ``cheap``); model ids come from configuration.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from stock_analyzer.config import MissingCredential, Settings
from stock_analyzer.store import Store, StoreLog, get_store, llm_totals
from stock_analyzer.store.base import KVCache
from stock_analyzer.store.fs import JsonlLog, read_jsonl

T = TypeVar("T", bound=BaseModel)
Role = Literal["main", "cheap"]

REPAIR_INSTRUCTION = (
    "Your previous reply could not be used: {error}\n"
    "Reply again with ONLY a JSON object that matches the required schema. No prose, no code fences."
)


# ---------------------------------------------------------------- data types


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None  # USD, as reported by the provider; 0 for cache hits and the fake


class DeltaEvent(BaseModel):
    type: Literal["delta"] = "delta"
    text: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    model: str
    usage: Usage
    latency_ms: int


StreamEvent = DeltaEvent | DoneEvent


class LLMError(RuntimeError):
    """The provider call failed (transport or API error)."""


class LLMOutputError(LLMError):
    """The model's output failed validation even after the repair retry."""

    def __init__(self, message: str, raw_output: str):
        super().__init__(f"{message}\n--- last raw output ---\n{raw_output}")
        self.raw_output = raw_output


class LLM(Protocol):
    def complete_json(
        self,
        role: Role,
        system: str,
        user: str,
        schema: type[T],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        purpose: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> T: ...

    def stream_text(
        self,
        role: Role,
        system: str,
        user: str,
        *,
        purpose: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> Iterator[StreamEvent]: ...


# ---------------------------------------------------------------- logging


class CallLog:
    """Append-only JSONL file of LLM calls (file backend). Never receives prompts or credentials."""

    def __init__(self, path: Path):
        self._log = JsonlLog(path)

    def write(self, **record: Any) -> None:
        self._log.append({"ts": datetime.now(UTC).isoformat(), **record})


def read_llm_totals(path: Path) -> dict[str, float | int]:
    """Totals over a JSONL LLM log file (file backend)."""
    return llm_totals(read_jsonl(path))


# ---------------------------------------------------------------- helpers


def schema_name(schema: type[BaseModel]) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in schema.__name__)[:64] or "output"


def cache_key(model: str, system: str, user: str, schema: dict[str, Any], params: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"model": model, "system": system, "user": user, "schema": schema, "params": dict(params)},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def parse_output(raw: str, schema: type[T]) -> T:
    """Parse and validate raw model output. Raises ValueError/ValidationError."""
    return schema.model_validate_json(_strip_fences(raw))


def _validation_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}" for err in exc.errors()
        )
    return str(exc)


def _usage_from(obj: Any) -> Usage:
    if obj is None:
        return Usage()
    data = obj if isinstance(obj, dict) else (obj.model_dump() if hasattr(obj, "model_dump") else vars(obj))
    cost = data.get("cost")
    return Usage(
        input_tokens=int(data.get("prompt_tokens") or 0),
        output_tokens=int(data.get("completion_tokens") or 0),
        cost=float(cost) if cost is not None else None,
    )


def _add(a: Usage, b: Usage) -> Usage:
    cost = None if a.cost is None and b.cost is None else (a.cost or 0) + (b.cost or 0)
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cost=cost,
    )


# ---------------------------------------------------------------- OpenRouter


class OpenRouterLLM:
    """Real gateway: OpenRouter via the OpenAI-compatible client."""

    def __init__(self, settings: Settings, *, client: Any | None = None, store: Store | None = None):
        self.settings = settings
        self._client = client
        # the store opens lazily, so constructing the gateway never needs a key or touches storage
        self.store: Store = store if store is not None else get_store(settings)
        self.log = StoreLog(self.store, "llm")

    @property
    def cache(self) -> KVCache:
        return self.store.cache("llm")

    @property
    def client(self) -> Any:
        if self._client is None:
            if self.settings.openrouter_api_key is None:
                raise MissingCredential("OPENROUTER_API_KEY", "A live LLM call")
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self.settings.openrouter_base_url,
                api_key=self.settings.openrouter_api_key.get_secret_value(),
                timeout=self.settings.llm_timeout_s,
                max_retries=2,
            )
        return self._client

    # -- structured

    def complete_json(
        self,
        role: Role,
        system: str,
        user: str,
        schema: type[T],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        purpose: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> T:
        model = self.settings.model_for(role)
        params = {"max_tokens": self.settings.llm_max_tokens, "temperature": 0, **(params or {})}
        json_schema = schema.model_json_schema()
        key = cache_key(model, system, user, {"schema": json_schema, "tools": list(tools or [])}, params)

        cached = self.cache.get(key)
        if cached is not None:
            self.log.write(
                model=model,
                purpose=purpose,
                input_tokens=0,
                output_tokens=0,
                cost=0.0,
                latency_ms=0,
                cache_hit=True,
                ok=True,
                attempts=0,
            )
            return parse_output(cached, schema)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name(schema), "strict": True, "schema": json_schema},
            },
            "extra_body": {"usage": {"include": True}},
            **params,
        }
        if tools:
            request["tools"] = list(tools)

        total = Usage()
        started = time.perf_counter()
        raw = ""
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                response = self.client.chat.completions.create(**request)
            except MissingCredential:
                raise
            except Exception as exc:  # transport / API error
                self._log_failure(model, purpose, total, started, attempt, repr(exc))
                raise LLMError(f"LLM call failed ({purpose or model}): {exc}") from exc
            total = _add(total, _usage_from(getattr(response, "usage", None)))
            raw = (response.choices[0].message.content or "") if response.choices else ""
            try:
                result = parse_output(raw, schema)
            except (ValidationError, ValueError) as exc:
                last_error = exc
                if attempt == 1:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": REPAIR_INSTRUCTION.format(error=_validation_message(exc)),
                        },
                    ]
                    request["messages"] = messages
                    continue
                break
            self.cache.set(key, raw)
            self.log.write(
                model=model,
                purpose=purpose,
                input_tokens=total.input_tokens,
                output_tokens=total.output_tokens,
                cost=total.cost,
                latency_ms=int((time.perf_counter() - started) * 1000),
                cache_hit=False,
                ok=True,
                attempts=attempt,
            )
            return result

        message = f"LLM output failed validation after one repair ({purpose or model}): {_validation_message(last_error)}"
        self._log_failure(model, purpose, total, started, 2, message)
        raise LLMOutputError(message, raw)

    def _log_failure(
        self, model: str, purpose: str, usage: Usage, started: float, attempts: int, error: str
    ) -> None:
        self.log.write(
            model=model,
            purpose=purpose,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost=usage.cost,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cache_hit=False,
            ok=False,
            attempts=attempts,
            error=error[:500],
        )

    # -- streaming

    def stream_text(
        self,
        role: Role,
        system: str,
        user: str,
        *,
        purpose: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> Iterator[StreamEvent]:
        model = self.settings.model_for(role)
        params = {"max_tokens": self.settings.llm_max_tokens, **(params or {})}
        started = time.perf_counter()
        usage = Usage()
        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                stream=True,
                stream_options={"include_usage": True},
                extra_body={"usage": {"include": True}},
                **params,
            )
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = _usage_from(chunk.usage)
                for choice in getattr(chunk, "choices", None) or []:
                    text = getattr(choice.delta, "content", None)
                    if text:
                        yield DeltaEvent(text=text)
        except MissingCredential:
            raise
        except GeneratorExit:
            self._log_failure(model, purpose, usage, started, 1, "cancelled by client")
            raise
        except Exception as exc:
            self._log_failure(model, purpose, usage, started, 1, repr(exc))
            raise LLMError(f"LLM stream failed ({purpose or model}): {exc}") from exc
        latency = int((time.perf_counter() - started) * 1000)
        self.log.write(
            model=model,
            purpose=purpose,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost=usage.cost,
            latency_ms=latency,
            cache_hit=False,
            ok=True,
            attempts=1,
            stream=True,
        )
        yield DoneEvent(model=model, usage=usage, latency_ms=latency)


# ---------------------------------------------------------------- Fake


def example_from_schema(schema: Mapping[str, Any], defs: Mapping[str, Any] | None = None) -> Any:
    """A minimal value valid for a pydantic JSON schema (used by FakeLLM)."""
    defs = defs if defs is not None else schema.get("$defs", {})
    if "$ref" in schema:
        return example_from_schema(defs[schema["$ref"].split("/")[-1]], defs)
    if "default" in schema:
        return schema["default"]
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"] or schema[key]
            return example_from_schema(options[0], defs)
    typ = schema.get("type")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), "null")
    if typ == "object" or "properties" in schema:
        props = schema.get("properties", {})
        required = schema.get("required", list(props))
        return {k: example_from_schema(v, defs) for k, v in props.items() if k in required}
    if typ == "array":
        n = schema.get("minItems", 0)
        return [example_from_schema(schema.get("items", {}), defs) for _ in range(n)]
    if typ == "string":
        return "x" * max(schema.get("minLength", 0), 1) if schema.get("minLength") else "טקסט"
    if typ == "integer":
        return int(schema.get("minimum", 0))
    if typ == "number":
        return float(schema.get("minimum", 0))
    if typ == "boolean":
        return False
    return None


@dataclass
class FakeCall:
    kind: Literal["json", "stream"]
    role: str
    model: str
    system: str
    user: str
    purpose: str
    schema: str | None = None


ScriptEntry = str | Mapping[str, Any] | BaseModel | Callable[["FakeCall"], Any]


@dataclass
class FakeLLM:
    """Offline LLM with the same interface. No network, no key, zero cost.

    ``script`` maps a purpose label to a response (JSON text, dict, model instance, or a
    callable taking the :class:`FakeCall`). A list value is consumed in order, one item per
    call. Unscripted structured calls return a schema-derived minimal object; unscripted
    streams echo a short Hebrew answer.
    """

    settings: Settings | None = None
    store: Store | None = None
    script: dict[str, ScriptEntry | list[ScriptEntry]] = field(default_factory=dict)
    chunk_chars: int = 12
    calls: list[FakeCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.store is None and self.settings is not None:
            self.store = get_store(self.settings)
        self.log = StoreLog(self.store, "llm") if self.store is not None else None

    def _model(self, role: str) -> str:
        return f"fake/{self.settings.model_for(role) if self.settings else role}"

    def _next(self, purpose: str, call: FakeCall) -> Any:
        entry = self.script.get(purpose, self.script.get("*"))
        if isinstance(entry, list):
            if not entry:
                raise LLMError(f"FakeLLM script for {purpose!r} is exhausted")
            entry = entry.pop(0)
        if callable(entry) and not isinstance(entry, BaseModel):
            entry = entry(call)
        return entry

    def _record(self, model: str, purpose: str, inp: int, out: int, stream: bool) -> None:
        if self.log:
            self.log.write(
                model=model,
                purpose=purpose,
                input_tokens=inp,
                output_tokens=out,
                cost=0.0,
                latency_ms=0,
                cache_hit=False,
                ok=True,
                attempts=1,
                stream=stream,
                fake=True,
            )

    def complete_json(
        self,
        role: Role,
        system: str,
        user: str,
        schema: type[T],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        purpose: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> T:
        model = self._model(role)
        call = FakeCall("json", role, model, system, user, purpose, schema.__name__)
        self.calls.append(call)
        entry = self._next(purpose, call)
        if entry is None:
            value: Any = example_from_schema(schema.model_json_schema())
            result = schema.model_validate(value)
        elif isinstance(entry, BaseModel):
            result = schema.model_validate(entry.model_dump())
        elif isinstance(entry, str):
            try:
                result = parse_output(entry, schema)
            except (ValidationError, ValueError) as exc:
                raise LLMOutputError(
                    f"FakeLLM scripted output invalid: {_validation_message(exc)}", entry
                ) from exc
        else:
            result = schema.model_validate(entry)
        self._record(model, purpose, len(system + user) // 4, len(result.model_dump_json()) // 4, False)
        return result

    def stream_text(
        self,
        role: Role,
        system: str,
        user: str,
        *,
        purpose: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> Iterator[StreamEvent]:
        model = self._model(role)
        call = FakeCall("stream", role, model, system, user, purpose)
        self.calls.append(call)
        entry = self._next(purpose, call)
        text = str(entry) if entry is not None else "תשובה לדוגמה מהמודל המדומה, על סמך הקטעים שסופקו."
        for i in range(0, len(text), self.chunk_chars):
            yield DeltaEvent(text=text[i : i + self.chunk_chars])
        usage = Usage(input_tokens=len(system + user) // 4, output_tokens=max(len(text) // 4, 1), cost=0.0)
        self._record(model, purpose, usage.input_tokens, usage.output_tokens, True)
        yield DoneEvent(model=model, usage=usage, latency_ms=0)


def get_llm(settings: Settings, store: Store | None = None) -> LLM:
    """The configured gateway: FakeLLM when ``LLM_FAKE`` is on, OpenRouter otherwise."""
    if settings.llm_fake:
        return FakeLLM(settings=settings, store=store)
    return OpenRouterLLM(settings, store=store)
