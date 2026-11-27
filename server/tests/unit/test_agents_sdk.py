"""Spike: pins down the parts of the OpenAI Agents SDK that the gateway model relies on (design D8).

The gateway caches agent turns by storing ``ModelResponse`` objects as JSON and replaying them.
These tests fail loudly if a future SDK release changes that contract.

Contract recorded for ``openai-agents==0.26.0``::

    Model.get_response(self, system_instructions: str | None,
                       input: str | list[TResponseInputItem],
                       model_settings: ModelSettings, tools: list[Tool],
                       output_schema: AgentOutputSchemaBase | None,
                       handoffs: list[Handoff], tracing: ModelTracing, *,
                       previous_response_id: str | None, conversation_id: str | None,
                       prompt: ResponsePromptParam | None) -> ModelResponse

    ModelResponse(output: list[TResponseOutputItem], usage: Usage, response_id: str | None,
                  request_id: str | None = None, raw_usage: dict[str, Any] | None = None)

``ModelSettings(preserve_raw_usage=True)`` keeps the provider's usage payload in ``raw_usage``,
which is where OpenRouter's ``cost`` arrives (it is not part of the SDK's ``Usage``).
"""

from __future__ import annotations

import asyncio
import json

from agents import Agent, ModelSettings, Runner, function_tool
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from pydantic import BaseModel, TypeAdapter

ADAPTER = TypeAdapter(ModelResponse)


def tool_call_response(name: str, arguments: dict) -> ModelResponse:
    call = ResponseFunctionToolCall(
        type="function_call", call_id="call_1", name=name, arguments=json.dumps(arguments), id="fc_1"
    )
    return ModelResponse(
        output=[call],
        usage=Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15),
        response_id=None,
        raw_usage={"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
    )


def final_response(text: str) -> ModelResponse:
    message = ResponseOutputMessage(
        type="message",
        id="msg_1",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )
    return ModelResponse(
        output=[message], usage=Usage(requests=1, input_tokens=20, output_tokens=8), response_id=None
    )


def roundtrip(response: ModelResponse) -> ModelResponse:
    stored = json.dumps(ADAPTER.dump_python(response, mode="json", by_alias=True), ensure_ascii=False)
    return ADAPTER.validate_python(json.loads(stored))


def test_model_response_json_roundtrip():
    for original in (tool_call_response("add", {"a": 1, "b": 2}), final_response('{"total": "3"}')):
        loaded = roundtrip(original)
        assert loaded == original
        assert type(loaded.output[0]) is type(original.output[0])
    assert roundtrip(tool_call_response("x", {})).raw_usage["cost"] == 0.0001


def test_preserve_raw_usage_setting_exists():
    assert ModelSettings(preserve_raw_usage=True).preserve_raw_usage is True


class Total(BaseModel):
    total: str


class ReplayModel(Model):
    """Answers from JSON-stored responses, as the gateway cache will."""

    def __init__(self, stored: list[str]):
        self.stored = list(stored)
        self.calls: list[dict] = []

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kw
    ):
        self.calls.append(
            {
                "system": system_instructions,
                "input": input,
                "tools": [t.name for t in tools],
                "schema": output_schema,
            }
        )
        return ADAPTER.validate_python(json.loads(self.stored.pop(0)))

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError


def test_agent_runs_a_tool_loop_from_stored_responses():
    seen: list[tuple[int, int]] = []

    @function_tool
    def add(a: int, b: int) -> str:
        """Add two integers."""
        seen.append((a, b))
        return str(a + b)

    stored = [
        json.dumps(ADAPTER.dump_python(r, mode="json", by_alias=True))
        for r in (tool_call_response("add", {"a": 2, "b": 3}), final_response('{"total": "5"}'))
    ]
    model = ReplayModel(stored)
    agent = Agent(name="adder", instructions="Use the tool.", model=model, tools=[add], output_type=Total)

    result = asyncio.run(Runner.run(agent, "add 2 and 3", max_turns=4))

    assert result.final_output == Total(total="5")
    assert seen == [(2, 3)]  # the real tool ran with the stored call's arguments
    assert len(model.calls) == 2
    assert model.calls[0]["tools"] == ["add"]
    assert model.calls[0]["schema"].json_schema()["required"] == ["total"]
    # the second turn's input carries the tool result back to the model
    assert any(item.get("type") == "function_call_output" for item in model.calls[1]["input"])
