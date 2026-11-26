"""OSINT agents on the OpenAI Agents SDK over OpenRouter (design D1, D4, D7, D9).

Flow: the orchestrator calls six specialist agents as tools (one per area); each specialist searches with
``web_search`` and returns an :class:`AreaReport`, which is collected into the :class:`RunState`. Areas the
orchestrator skipped are researched directly afterwards. Findings are verified in code, then the
synthesizer turns the kept findings into a :class:`Scorecard`, which is checked in code too.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from string import Template
from typing import Any, Literal

from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    RunContextWrapper,
    RunHooks,
    Runner,
    function_tool,
    set_tracing_disabled,
)
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage as AgentUsage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from stock_analyzer.config import MissingCredential, Settings
from stock_analyzer.errors import NoFindings
from stock_analyzer.osint.models import (
    AREA_INFO,
    AREAS,
    Area,
    AreaReport,
    KeptFinding,
    RunState,
    Scorecard,
)
from stock_analyzer.osint.search import SearchBackend, run_search
from stock_analyzer.osint.verify import check_scorecard, verify_findings
from stock_analyzer.store import StoreLog

AGENT_PURPOSE = "osint-agent:{name}"
Role = Literal["orchestrator", "specialist", "synthesizer"]
ModelFactory = Callable[[Role, Area | None], Model]


def tool_name(area: Area) -> str:
    return f"research_{area}"


def load_prompt(prompts_dir: Path, name: str, **values: str) -> str:
    text = (prompts_dir / "osint" / f"{name}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute(values)


# ---------------------------------------------------------------- usage logging


class OsintHooks(RunHooks[RunState]):
    """Logs every agent model call to the usage log (source ``llm``, purpose ``osint-agent:<name>``)."""

    def __init__(self, log: StoreLog | None, model: str):
        self.log = log
        self.model = model
        self._started: dict[str, list[float]] = {}

    async def on_agent_start(self, context: RunContextWrapper[RunState], agent: Agent) -> None:  # type: ignore[override]
        state = context.context
        if agent.name == "osint_orchestrator":
            state.progress("orchestrator")
        elif agent.name == "osint_synthesizer":
            state.progress("synthesis")
        elif agent.name.startswith("osint_") and agent.name[len("osint_") :] in AREAS:
            state.progress("area_start", area=agent.name[len("osint_") :])  # type: ignore[arg-type]

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:  # type: ignore[override]
        self._started.setdefault(agent.name, []).append(time.perf_counter())

    async def on_llm_end(
        self, context: RunContextWrapper[RunState], agent: Agent, response: ModelResponse
    ) -> None:
        starts = self._started.get(agent.name) or [time.perf_counter()]
        started = starts.pop(0)
        raw = response.raw_usage or {}
        cost = raw.get("cost") if isinstance(raw, Mapping) else None
        cost = float(cost) if cost is not None else None
        context.context.add_cost(cost)
        if self.log is not None:
            self.log.write(
                model=self.model,
                purpose=AGENT_PURPOSE.format(name=agent.name),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost=cost,
                latency_ms=int((time.perf_counter() - started) * 1000),
                cache_hit=False,
                ok=True,
                attempts=1,
            )


# ---------------------------------------------------------------- models


def live_model_factory(settings: Settings) -> ModelFactory:
    if settings.openrouter_api_key is None:
        raise MissingCredential("OPENROUTER_API_KEY", "OSINT research")
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key.get_secret_value(),
        timeout=settings.llm_timeout_s,
        max_retries=2,
    )
    model = OpenAIChatCompletionsModel(model=settings.model_osint, openai_client=client)
    return lambda role, area: model


MODEL_SETTINGS = ModelSettings(
    include_usage=True,
    preserve_raw_usage=True,  # keeps OpenRouter's usage.cost for the usage log
    extra_body={"usage": {"include": True}},
)


# ---------------------------------------------------------------- pipeline


def _report_digest(area: Area, report: AreaReport) -> str:
    """What the orchestrator sees from a specialist: enough to decide on follow-ups."""
    return json.dumps(
        {
            "area": area,
            "summary": report.summary,
            "findings": [
                {"claim": f.claim, "signal": f.signal, "published_at": f.published_at}
                for f in report.findings
            ],
        },
        ensure_ascii=False,
    )


def _findings_payload(kept: list[KeptFinding]) -> str:
    return json.dumps(
        {
            "findings": [
                {
                    "id": f.id,
                    "area": f.area,
                    "claim": f.claim,
                    "signal": f.signal,
                    "confidence": f.confidence,
                    "source": f.source_title or f.source_url,
                    "published_at": f.published_at,
                    "derived_from_filing": f.derived_from_filing,
                }
                for f in kept
            ]
        },
        ensure_ascii=False,
    )


async def run_pipeline(
    settings: Settings,
    state: RunState,
    *,
    backend: SearchBackend,
    log: StoreLog | None,
    model_factory: ModelFactory,
    today: date,
) -> tuple[Scorecard, list[KeptFinding], dict[str, int]]:
    set_tracing_disabled(True)  # tracing would upload to OpenAI's platform; there is no OpenAI key
    company = " / ".join(state.company_names)
    common = {
        "market_context": load_prompt(settings.prompts_dir, "israel_market"),
        "company": company,
        "ticker": state.ticker,
        "today": today.isoformat(),
        "window_start": state.window_start.isoformat(),
    }
    hooks = OsintHooks(log, settings.model_osint)

    @function_tool
    async def web_search(ctx: RunContextWrapper[RunState], query: str) -> str:
        """Search the web. Returns results (url, title, snippet), a short summary, and searches left.

        Args:
            query: What to search for, in Hebrew or English. Include the company's name.
        """
        return json.dumps(await run_search(ctx.context, backend, log, query), ensure_ascii=False)

    specialists: dict[Area, Agent[RunState]] = {}
    for area in AREAS:
        name_he, desc = AREA_INFO[area]
        specialists[area] = Agent[RunState](
            name=f"osint_{area}",
            instructions=load_prompt(
                settings.prompts_dir, "specialist", area_name=f"{area} ({name_he})", area_desc=desc, **common
            ),
            tools=[web_search],
            output_type=AreaReport,
            model=model_factory("specialist", area),
            model_settings=MODEL_SETTINGS,
        )

    def collector(area: Area):
        async def extract(result: Any) -> str:
            report = result.final_output
            if isinstance(report, AreaReport):
                state.reports.append((area, report))
                state.progress("area_done", area=area)
                return _report_digest(area, report)
            return json.dumps({"area": area, "error": "no structured report"})

        return extract

    tools = [
        specialists[area].as_tool(
            tool_name=tool_name(area),
            tool_description=f"Research the '{area}' area: {AREA_INFO[area][1]}",
            custom_output_extractor=collector(area),
            max_turns=settings.osint_max_turns,
            hooks=hooks,
        )
        for area in AREAS
    ]
    orchestrator = Agent[RunState](
        name="osint_orchestrator",
        instructions=load_prompt(
            settings.prompts_dir,
            "orchestrator",
            tools="\n".join(f"- {tool_name(a)}: {AREA_INFO[a][1]}" for a in AREAS),
            **common,
        ),
        tools=[web_search, *tools],  # web_search lets it profile the company before briefing specialists
        model=model_factory("orchestrator", None),
        model_settings=MODEL_SETTINGS,
    )
    try:
        await Runner.run(
            orchestrator,
            f"Research {company} ({state.ticker}) across all six areas.",
            context=state,
            max_turns=settings.osint_max_turns,
            hooks=hooks,
        )
    except MissingCredential:
        raise
    except Exception:  # the orchestrator failing must not lose the findings collected so far
        pass

    # areas the orchestrator never covered are researched directly
    for area in AREAS:
        if any(a == area for a, _ in state.reports):
            continue
        try:
            result = await Runner.run(
                specialists[area],
                f"Research the {area} area for {company} ({state.ticker}).",
                context=state,
                max_turns=settings.osint_max_turns,
                hooks=hooks,
            )
        except MissingCredential:
            raise
        except Exception:
            continue
        if isinstance(result.final_output, AreaReport):
            state.reports.append((area, result.final_output))
            state.progress("area_done", area=area)

    kept, dropped = verify_findings(state)
    if not kept:
        raise NoFindings(
            f"no usable findings for {state.ticker} (searches used: {state.searches_used}, dropped: {dropped})"
        )

    synthesizer = Agent[RunState](
        name="osint_synthesizer",
        instructions=load_prompt(settings.prompts_dir, "synthesizer", **common),
        output_type=Scorecard,
        model=model_factory("synthesizer", None),
        model_settings=MODEL_SETTINGS,
    )
    result = await Runner.run(synthesizer, _findings_payload(kept), context=state, max_turns=3, hooks=hooks)
    return check_scorecard(result.final_output, kept), kept, dropped


# ---------------------------------------------------------------- offline model (LLM_FAKE and tests)


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"type": "message", "role": "user", "content": value}]
    out = []
    for item in value or []:
        if isinstance(item, Mapping):
            out.append(dict(item))
        elif hasattr(item, "model_dump"):
            out.append(item.model_dump())
    return out


def _message(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id=f"msg_{uuid.uuid4().hex[:8]}",
        content=[ResponseOutputText(annotations=[], text=text, type="output_text")],
        role="assistant",
        status="completed",
        type="message",
    )


def _call(name: str, arguments: dict[str, Any]) -> ResponseFunctionToolCall:
    return ResponseFunctionToolCall(
        arguments=json.dumps(arguments, ensure_ascii=False),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
        name=name,
        type="function_call",
        id=f"fc_{uuid.uuid4().hex[:8]}",
        status="completed",
    )


def _user_text(items: list[dict[str, Any]]) -> str:
    for item in reversed(items):
        if item.get("role") == "user":
            content = item.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(str(c.get("text", "")) for c in content if isinstance(c, Mapping))
    return ""


class FakeAgentModel(Model):
    """Scripted SDK model: no network. Specialists search once and report what the search returned."""

    def __init__(self, role: Role, area: Area | None, ticker: str, *, skip_areas: tuple[Area, ...] = ()):
        self.role = role
        self.area = area
        self.ticker = ticker
        self.skip_areas = skip_areas

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):  # type: ignore[override]
        items = _items(input)
        outputs = [i for i in items if i.get("type") == "function_call_output"]
        usage = AgentUsage(requests=1, input_tokens=100, output_tokens=50, total_tokens=150)

        if self.role == "orchestrator":
            if outputs:
                out: list[Any] = [_message("Covered all areas.")]
            else:
                out = [
                    _call(tool_name(a), {"input": f"Look into {a}."})
                    for a in AREAS
                    if a not in self.skip_areas
                ]
        elif self.role == "specialist":
            if not outputs:
                out = [_call("web_search", {"query": f"{self.ticker} {self.area}"})]
            else:
                results = json.loads(str(outputs[-1].get("output") or "{}")).get("results") or []
                findings = [
                    {
                        "claim": f"{self.area}: {r['title']}",
                        "signal": ("positive", "negative", "neutral")[n % 3],
                        "confidence": "medium",
                        "source_url": r["url"],
                        "source_title": r["title"],
                        "published_at": "2026-10-01",
                        "derived_from_filing": False,
                    }
                    for n, r in enumerate(results[:2])
                ]
                out = [
                    _message(
                        json.dumps({"findings": findings, "summary": f"Example summary for {self.area}."})
                    )
                ]
        else:
            payload = json.loads(_user_text(items) or "{}")
            findings = payload.get("findings") or []
            ids = [f["id"] for f in findings]
            card = {
                "overall_label": "watch",
                "overall_rationale": "סיכון בינוני על סמך הממצאים לדוגמה.",
                "areas": [
                    {
                        "area": a,
                        "label": "stable",
                        "assessment": "הערכה לדוגמה.",
                        "finding_ids": [f["id"] for f in findings if f["area"] == a],
                    }
                    for a in AREAS
                ],
                "risks": [{"text": "סיכון לדוגמה.", "finding_ids": ids[:1]}],
                "strengths": [{"text": "חוזקה לדוגמה.", "finding_ids": ids[1:2] or ids[:1]}],
                "summary_he": "סיכום לדוגמה של יציבות החברה.",
            }
            out = [_message(json.dumps(card, ensure_ascii=False))]
        return ModelResponse(output=out, usage=usage, response_id=None)

    def stream_response(self, *args, **kwargs):  # pragma: no cover - streaming is not used
        raise NotImplementedError("FakeAgentModel does not stream")


def fake_model_factory(ticker: str, *, skip_areas: tuple[Area, ...] = ()) -> ModelFactory:
    return lambda role, area: FakeAgentModel(role, area, ticker, skip_areas=skip_areas)
