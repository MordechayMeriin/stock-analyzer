"""OSINT agents on the OpenAI Agents SDK over OpenRouter (design D1, D4, D7, D9; improve-osint-evidence D1-D9).

Flow: the orchestrator profiles the company and calls eight specialist agents as tools (one per area); each
specialist searches with ``web_search`` and returns an :class:`AreaReport`, which is collected into the
:class:`RunState`. The orchestrator's final output is the :class:`CompanyProfile`. Areas the orchestrator
skipped are researched directly afterwards. Findings are verified in code, checked against their source
excerpts by a cheap verifier agent, and merged when a cheap grouper agent (or the exact pass) finds the same
event twice. The synthesizer turns the profile, merged findings and trend hints into a :class:`Scorecard`,
which is checked in code too.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
from stock_analyzer.osint.evidence import (
    apply_verdicts,
    claim_batches,
    exact_duplicate_groups,
    merge_findings,
    trend_hints,
    validate_groups,
)
from stock_analyzer.osint.models import (
    AREA_INFO,
    AREAS,
    Area,
    AreaReport,
    CompanyProfile,
    DuplicateGroups,
    KeptFinding,
    RunState,
    Scorecard,
    VerdictBatch,
)
from stock_analyzer.osint.search import SearchBackend, run_search
from stock_analyzer.osint.verify import check_scorecard, verify_findings
from stock_analyzer.store import StoreLog

AGENT_PURPOSE = "osint-agent:{name}"
Role = Literal["orchestrator", "specialist", "synthesizer", "verifier", "grouper"]
CHEAP_ROLES: tuple[Role, ...] = ("verifier", "grouper")  # run on MODEL_CHEAP (improve-osint-evidence D3-D4)
CHEAP_AGENTS = ("osint_verifier", "osint_grouper")


@dataclass
class PipelineResult:
    scorecard: Scorecard
    findings: list[KeptFinding]
    dropped: dict[str, int]
    merged: int
    profile: CompanyProfile | None


ModelFactory = Callable[[Role, Area | None], Model]


def tool_name(area: Area) -> str:
    return f"research_{area}"


def load_prompt(prompts_dir: Path, name: str, **values: str) -> str:
    text = (prompts_dir / "osint" / f"{name}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute(values)


# ---------------------------------------------------------------- usage logging


class OsintHooks(RunHooks[RunState]):
    """Logs every agent model call to the usage log (source ``llm``, purpose ``osint-agent:<name>``)."""

    def __init__(self, log: StoreLog | None, model: str, cheap_model: str | None = None):
        self.log = log
        self.model = model
        self.cheap_model = cheap_model or model
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
                model=self.cheap_model if agent.name in CHEAP_AGENTS else self.model,
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
    cheap = OpenAIChatCompletionsModel(model=settings.model_cheap, openai_client=client)
    return lambda role, area: cheap if role in CHEAP_ROLES else model


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


def _synthesis_payload(
    kept: list[KeptFinding], profile: CompanyProfile | None, hints: dict[Area, dict[str, int]]
) -> str:
    return json.dumps(
        {
            "profile": profile.model_dump() if profile else None,
            "findings": [
                {
                    "id": f.id,
                    "area": f.area,
                    "also_areas": f.also_areas,
                    "claim": f.claim,
                    "signal": f.signal,
                    "confidence": f.confidence,
                    "verdict": f.verdict,
                    "sources": 1 + len(f.also_sources),
                    "source": f.source_title or f.source_url,
                    "published_at": f.published_at,
                    "derived_from_filing": f.derived_from_filing,
                }
                for f in kept
            ],
            "trend_hints": hints,
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
) -> PipelineResult:
    set_tracing_disabled(True)  # tracing would upload to OpenAI's platform; there is no OpenAI key
    company = " / ".join(state.company_names)
    common = {
        "market_context": load_prompt(settings.prompts_dir, "israel_market"),
        "company": company,
        "ticker": state.ticker,
        "today": today.isoformat(),
        "window_start": state.window_start.isoformat(),
    }
    hooks = OsintHooks(log, settings.model_osint, settings.model_cheap)

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
        output_type=CompanyProfile,
        model=model_factory("orchestrator", None),
        model_settings=MODEL_SETTINGS,
    )
    profile: CompanyProfile | None = None
    try:
        orchestrated = await Runner.run(
            orchestrator,
            f"Research {company} ({state.ticker}) across all {len(AREAS)} areas.",
            context=state,
            max_turns=settings.osint_max_turns,
            hooks=hooks,
        )
        if isinstance(orchestrated.final_output, CompanyProfile):
            profile = orchestrated.final_output
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

    kept, dropped["unsupported"] = await _check_claims(settings, state, kept, model_factory, hooks)
    if not kept:
        raise NoFindings(f"no finding for {state.ticker} was supported by its source (dropped: {dropped})")
    kept, merged = await _merge_duplicates(settings, state, kept, model_factory, hooks)

    synthesizer = Agent[RunState](
        name="osint_synthesizer",
        instructions=load_prompt(settings.prompts_dir, "synthesizer", **common),
        output_type=Scorecard,
        model=model_factory("synthesizer", None),
        model_settings=MODEL_SETTINGS,
    )
    payload = _synthesis_payload(kept, profile, trend_hints(kept, today))
    result = await Runner.run(synthesizer, payload, context=state, max_turns=3, hooks=hooks)
    return PipelineResult(
        scorecard=check_scorecard(result.final_output, kept, profile),
        findings=kept,
        dropped=dropped,
        merged=merged,
        profile=profile,
    )


async def _check_claims(
    settings: Settings,
    state: RunState,
    kept: list[KeptFinding],
    model_factory: ModelFactory,
    hooks: OsintHooks,
) -> tuple[list[KeptFinding], int]:
    """Verdict per finding from the cheap verifier, in concurrent batches (improve-osint-evidence D3)."""
    verifier = Agent[RunState](
        name="osint_verifier",
        instructions=load_prompt(settings.prompts_dir, "verifier"),
        output_type=VerdictBatch,
        model=model_factory("verifier", None),
        model_settings=MODEL_SETTINGS,
    )

    async def check(batch: list[dict[str, str]]) -> dict[str, str]:
        try:
            result = await Runner.run(
                verifier,
                json.dumps({"findings": batch}, ensure_ascii=False),
                context=state,
                max_turns=2,
                hooks=hooks,
            )
        except MissingCredential:
            raise
        except Exception:  # a failed batch leaves its findings unverified (kept at low confidence)
            return {}
        out = result.final_output
        return {v.id: v.verdict for v in out.verdicts} if isinstance(out, VerdictBatch) else {}

    verdicts: dict[str, str] = {}
    for part in await asyncio.gather(*(check(b) for b in claim_batches(state, kept))):
        verdicts.update(part)
    return apply_verdicts(state, kept, verdicts)  # type: ignore[arg-type]


async def _merge_duplicates(
    settings: Settings,
    state: RunState,
    kept: list[KeptFinding],
    model_factory: ModelFactory,
    hooks: OsintHooks,
) -> tuple[list[KeptFinding], int]:
    """Exact pass in code, then one cheap grouper call over every claim (improve-osint-evidence D4)."""
    groups = exact_duplicate_groups(kept)
    if len(kept) >= 2:
        grouper = Agent[RunState](
            name="osint_grouper",
            instructions=load_prompt(settings.prompts_dir, "grouper"),
            output_type=DuplicateGroups,
            model=model_factory("grouper", None),
            model_settings=MODEL_SETTINGS,
        )
        payload = json.dumps(
            {
                "findings": [
                    {"id": f.id, "area": f.area, "published_at": f.published_at, "claim": f.claim}
                    for f in kept
                ]
            },
            ensure_ascii=False,
        )
        try:
            result = await Runner.run(grouper, payload, context=state, max_turns=2, hooks=hooks)
            if isinstance(result.final_output, DuplicateGroups):
                groups += validate_groups(result.final_output.groups, [f.id for f in kept])
        except MissingCredential:
            raise
        except Exception:  # without the grouper only exact duplicates are merged
            pass
    return merge_findings(kept, groups)


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

    def __init__(
        self,
        role: Role,
        area: Area | None,
        ticker: str,
        *,
        skip_areas: tuple[Area, ...] = (),
        verdicts: dict[str, str] | None = None,
        groups: list[list[str]] | None = None,
        fail_orchestrator: bool = False,
    ):
        self.role = role
        self.area = area
        self.ticker = ticker
        self.skip_areas = skip_areas
        self.verdicts = verdicts or {}  # claim text fragment -> verdict; default supported
        self.groups = groups or []  # groups of claim text fragments to report as duplicates
        self.fail_orchestrator = fail_orchestrator

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):  # type: ignore[override]
        items = _items(input)
        outputs = [i for i in items if i.get("type") == "function_call_output"]
        usage = AgentUsage(requests=1, input_tokens=100, output_tokens=50, total_tokens=150)

        if self.role == "orchestrator":
            if outputs and self.fail_orchestrator:
                raise RuntimeError("scripted orchestrator failure")
            if outputs:
                profile = {
                    "industry": "example industry",
                    "business_lines": ["main line"],
                    "controlling_shareholder": None,
                    "competitors": ["Rival Ltd."],
                    "regulator": "Example Authority",
                    "key_drivers": ["demand", "competition", "regulation"],
                }
                out: list[Any] = [_message(json.dumps(profile))]
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
        elif self.role == "verifier":
            batch = json.loads(_user_text(items) or "{}").get("findings") or []
            verdicts = []
            for f in batch:
                verdict = next((v for frag, v in self.verdicts.items() if frag in f["claim"]), "supported")
                verdicts.append({"id": f["id"], "verdict": verdict, "reason": "scripted"})
            out = [_message(json.dumps({"verdicts": verdicts}))]
        elif self.role == "grouper":
            findings = json.loads(_user_text(items) or "{}").get("findings") or []
            groups = [
                [f["id"] for f in findings if any(frag in f["claim"] for frag in g)] for g in self.groups
            ]
            out = [_message(json.dumps({"groups": [g for g in groups if len(g) >= 2]}))]
        else:
            payload = json.loads(_user_text(items) or "{}")
            findings = payload.get("findings") or []
            ids = [f["id"] for f in findings]
            drivers = (payload.get("profile") or {}).get("key_drivers") or ["demand"]
            card = {
                "overall_label": "watch",
                "overall_rationale": "סיכון בינוני על סמך הממצאים לדוגמה.",
                "overall_trend": "stable",
                "overall_trend_reason": "מגמה יציבה לדוגמה.",
                "key_drivers": [
                    {"driver": d, "status": "mixed", "explanation": "הסבר לדוגמה.", "finding_ids": ids[:1]}
                    for d in drivers[:2]
                ],
                "areas": [
                    {
                        "area": a,
                        "label": "stable",
                        "importance": "high" if a == "operations" else "medium",
                        "assessment": "הערכה לדוגמה.",
                        "trend": "improving",
                        "trend_reason": "מגמה לדוגמה.",
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


def fake_model_factory(
    ticker: str,
    *,
    skip_areas: tuple[Area, ...] = (),
    verdicts: dict[str, str] | None = None,
    groups: list[list[str]] | None = None,
    fail_orchestrator: bool = False,
) -> ModelFactory:
    return lambda role, area: FakeAgentModel(
        role,
        area,
        ticker,
        skip_areas=skip_areas,
        verdicts=verdicts,
        groups=groups,
        fail_orchestrator=fail_orchestrator,
    )
