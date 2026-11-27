"""The story pipeline (design D1, D10): code orchestrates, agents only at the leaves.

    prepare (no LLM): reports by as_of -> parse -> compare sections -> facts -> token budget
    run:   describe + change batches + explain per year, in parallel
           -> storyteller (tools) -> verify -> one repair turn -> render -> StoryRun

:func:`prepare_story` raises every input error before any LLM call, so the API can answer
with a plain error before it starts streaming. :func:`stream_story` is a sync generator of
progress events over the async core, consumed the same way by the API and the CLI.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import queue
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from stock_analyzer.agents_model import UsageTotals, run_agent
from stock_analyzer.diff.align import AlignedSection, Comparison, Report, compare_business
from stock_analyzer.errors import NotCached, StoryTooLarge, StoryVerificationFailed
from stock_analyzer.ingest.structure import STRUCTURE_VERSION
from stock_analyzer.services import filings as filings_service
from stock_analyzer.services import ratios as ratios_service
from stock_analyzer.services import reports
from stock_analyzer.services.companies import resolve_company
from stock_analyzer.services.context import Ctx
from stock_analyzer.store import Store
from stock_analyzer.story.agents import (
    ChangeNote,
    ChangeNotes,
    CompanyProfile,
    ManagementClaim,
    ManagementClaims,
    ModelFactory,
    StoryContext,
    change_agent,
    change_batches,
    describe_agent,
    describe_input,
    explain_agent,
    explain_input,
    prompt_hashes,
    storyteller_agent,
    storyteller_input,
)
from stock_analyzer.story.facts import Fact, FactRegistry, registry_from_analysis
from stock_analyzer.story.models import Story
from stock_analyzer.story.reading import ReadBudget, ReportLibrary
from stock_analyzer.story.render import RenderedFinding, RenderedParagraph, render_finding, render_paragraph
from stock_analyzer.story.select import story_reports
from stock_analyzer.story.verify import VerificationError, text_errors, verify_story

# ---------------------------------------------------------------- run record


class Citation(BaseModel):
    paragraph_id: str
    fiscal_year: int
    page_index: int
    page_printed: int | None
    node_id: str | None = None  # the deepest report section holding the paragraph (reader deep link)


class UnchangedSection(BaseModel):
    key: str
    title: str


class RenderedStory(BaseModel):
    what_it_does: list[RenderedParagraph]
    what_changed: list[RenderedParagraph]
    story_vs_numbers: list[RenderedFinding]
    unchanged_sections: list[UnchangedSection]


class VerificationAttempt(BaseModel):
    attempt: int
    errors: list[VerificationError]


class StoryUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model_turns: int


class StoryRun(BaseModel):
    """Everything a saved story needs to be shown again, unchanged (company-story spec)."""

    run_id: str
    ticker: str
    as_of: str
    created_at: str
    years: list[int]
    filing_ids: dict[str, int]
    rendered: RenderedStory
    story: Story
    facts: list[Fact]  # the registry the story was written against
    citations: dict[str, Citation]
    profile: CompanyProfile | None
    change_notes: list[ChangeNote]
    claims: dict[str, list[ManagementClaim]]
    verification: list[VerificationAttempt]
    warnings: list[str]
    models: dict[str, str]
    prompt_hashes: dict[str, str]
    config_hash: str
    usage: StoryUsage


class StoryEvent(BaseModel):
    type: Literal["progress", "done", "error"]
    step: str
    message: str
    data: Any = None


# ---------------------------------------------------------------- prepare (no LLM)


@dataclass
class PreparedStory:
    ticker: str
    as_of: date
    years: list[int]
    filing_ids: dict[int, int]
    context: StoryContext
    comparison: Comparison
    describe_text: str
    change_texts: list[str]
    explain_texts: dict[int, str]
    estimated_tokens: int
    store: Store | None = None


def prepare_story(ctx: Ctx, ticker: str, *, as_of: date | None = None) -> PreparedStory:
    """Everything up to the first LLM call; raises input errors (reports, budget) early."""
    company = resolve_company(ctx, ticker)
    cutoff = as_of or datetime.now(UTC).date()
    chosen = story_reports(
        filings_service.company_filings(ctx, company.ticker), cutoff, ticker=company.ticker
    )
    years = [y for y, _ in chosen]

    loaded = {y: reports.load_parsed(ctx, company.ticker, y) for y in years}
    library = ReportLibrary({y: (parsed, structure) for y, (parsed, structure, _meta) in loaded.items()})
    s = ctx.settings
    comparison = compare_business(
        company.ticker,
        [Report(y, parsed, structure) for y, (parsed, structure, _m) in loaded.items()],
        unchanged_threshold=s.diff_unchanged_threshold,
        title_threshold=s.diff_title_match_threshold,
        content_threshold=s.diff_content_match_threshold,
    )
    analysis = ratios_service.analyze(ctx, company.ticker, as_of=cutoff)
    registry = registry_from_analysis(analysis, years, library.paragraphs)
    story_ctx = StoryContext(settings=s, registry=registry, library=library, years=years)

    describe_text = describe_input(story_ctx)
    change_texts = change_batches(story_ctx, comparison)
    explain_texts = {y: t for y in years if (t := explain_input(story_ctx, y))}
    estimate = ReadBudget(tokens=0, chars_per_token=s.chars_per_token).estimate
    # report text the run may send: the fixed inputs, plus what the describe agent and the
    # storyteller may read with their tools
    estimated = (
        estimate(describe_text)
        + sum(estimate(t) for t in change_texts)
        + sum(estimate(t) for t in explain_texts.values())
        + 2 * s.story_reader_budget_tokens
    )
    if estimated > s.story_max_tokens:
        raise StoryTooLarge(
            f"this story would send about {estimated:,} tokens of report text, over the "
            f"{s.story_max_tokens:,}-token budget (STORY_MAX_TOKENS)"
        )
    return PreparedStory(
        ticker=company.ticker,
        as_of=cutoff,
        years=years,
        filing_ids={y: meta.filing_id for y, (_p, _s, meta) in loaded.items()},
        context=story_ctx,
        comparison=comparison,
        describe_text=describe_text,
        change_texts=change_texts,
        explain_texts=explain_texts,
        estimated_tokens=estimated,
        store=ctx.store,
    )


# ---------------------------------------------------------------- run (agents)


def _clean_pids(ids: list[str], prep: PreparedStory, where: str, warnings: list[str]) -> list[str]:
    known = [i for i in ids if i in prep.context.library.paragraphs]
    if len(known) < len(ids):
        warnings.append(f"{where}: dropped unknown paragraph ids {sorted(set(ids) - set(known))}")
    return known


def _check_reader_text(text: str, prep: PreparedStory, where: str, warnings: list[str]) -> bool:
    # reader text is not shown; reports naturally mention the comparison year and later events
    years = range(prep.years[0] - 1, prep.years[-1] + 2)
    problems = text_errors(text, prep.context.registry, years)
    if problems:
        warnings.append(f"{where}: dropped ({'; '.join(problems)})")
    return not problems


def _unchanged(comparison: Comparison) -> list[AlignedSection]:
    return [
        s
        for s in comparison.sections
        if s.level == 2
        and len(s.node_ids) == len(comparison.years)
        and all(p.status == "unchanged" for p in s.pairs)
    ]


async def _build(prep: PreparedStory, make_model: ModelFactory, emit) -> StoryRun:
    ctx = prep.context
    ctx.emit = emit
    s = ctx.settings
    usage = UsageTotals()
    warnings: list[str] = []

    async def reader(name: str, agent, text: str):
        emit("agent_start", f"{name} started", {"agent": name})
        try:
            out = await run_agent(agent, text, max_turns=s.agent_max_turns, usage=usage)
        except Exception as exc:  # one failed reader does not sink the story; it is recorded
            warnings.append(f"{name} failed: {exc}")
            emit("agent_failed", f"{name} failed: {exc}", {"agent": name})
            return None
        emit("agent_done", f"{name} finished", {"agent": name})
        return out

    jobs = [reader("describe", describe_agent(ctx, make_model), prep.describe_text)]
    jobs += [
        reader(f"change-{i}", change_agent(ctx, make_model, i), text)
        for i, text in enumerate(prep.change_texts, 1)
    ]
    explain_years = list(prep.explain_texts)
    jobs += [
        reader(f"explain-{y}", explain_agent(ctx, make_model, y), prep.explain_texts[y])
        for y in explain_years
    ]
    for y in prep.years:
        if y not in prep.explain_texts:
            warnings.append(f"no directors' report explanations found for FY{y}")
    results = await asyncio.gather(*jobs)

    profile: CompanyProfile | None = results[0]
    if profile is not None:
        kept = []
        for i, item in enumerate(profile.items):
            if _check_reader_text(item.text_he, prep, f"profile[{i}]", warnings):
                item.paragraph_ids = _clean_pids(item.paragraph_ids, prep, f"profile[{i}]", warnings)
                kept.append(item)
        profile = CompanyProfile(items=kept)
    notes: list[ChangeNote] = []
    for batch in results[1 : 1 + len(prep.change_texts)]:
        for note in (batch or ChangeNotes(notes=[])).notes:
            where = f"change {note.section_key}"
            if _check_reader_text(note.what_changed_he, prep, where, warnings):
                note.old_paragraph_ids = _clean_pids(note.old_paragraph_ids, prep, where, warnings)
                note.new_paragraph_ids = _clean_pids(note.new_paragraph_ids, prep, where, warnings)
                notes.append(note)
    claims: dict[int, list[ManagementClaim]] = {}
    for y, out in zip(explain_years, results[1 + len(prep.change_texts) :], strict=True):
        kept_claims = []
        for i, claim in enumerate((out or ManagementClaims(claims=[])).claims):
            where = f"explain FY{y}[{i}]"
            if _check_reader_text(claim.claim_he, prep, where, warnings):
                claim.paragraph_ids = _clean_pids(claim.paragraph_ids, prep, where, warnings)
                kept_claims.append(claim)
        claims[y] = kept_claims

    unchanged = _unchanged(prep.comparison)
    base_input = storyteller_input(ctx, profile, notes, claims, unchanged)
    attempts: list[VerificationAttempt] = []
    story_input = base_input
    story: Story | None = None
    for attempt in (1, 2):
        emit(
            "agent_start",
            "storyteller started" if attempt == 1 else "storyteller repairing",
            {"agent": "storyteller"},
        )
        story = await run_agent(
            storyteller_agent(ctx, make_model), story_input, max_turns=s.story_writer_max_turns, usage=usage
        )
        emit("agent_done", "storyteller finished", {"agent": "storyteller"})
        emit("verify", f"verifying the story (attempt {attempt})", {"attempt": attempt})
        errors = verify_story(story, ctx.registry, ctx.library.paragraphs, prep.years)
        attempts.append(VerificationAttempt(attempt=attempt, errors=errors))
        if not errors:
            break
        emit("verify", f"{len(errors)} verification errors", {"attempt": attempt, "errors": len(errors)})
        story_input = (
            base_input
            + "\n\n## Your previous answer\n\n"
            + story.model_dump_json(indent=1)
            + "\n\n## Errors to fix\n\n"
            + "\n".join(f"- [{e.where}] rule {e.rule}: {e.message}" for e in errors)
        )
    if attempts[-1].errors:
        raise StoryVerificationFailed(
            f"the story failed verification after one repair ({len(attempts[-1].errors)} errors)",
            [e.model_dump() for e in attempts[-1].errors],
        )
    assert story is not None

    rendered = RenderedStory(
        what_it_does=[render_paragraph(p, ctx.registry) for p in story.what_it_does],
        what_changed=[render_paragraph(p, ctx.registry) for p in story.what_changed],
        story_vs_numbers=[render_finding(f, ctx.registry) for f in story.story_vs_numbers],
        unchanged_sections=[UnchangedSection(key=u.key, title=u.title) for u in unchanged],
    )
    cited = {
        pid
        for item in [*story.what_it_does, *story.what_changed, *story.story_vs_numbers]
        for pid in item.paragraph_ids
    }
    citations = {}
    for pid in sorted(cited):
        p = ctx.library.paragraphs[pid]
        _, structure = ctx.library.reports[p.fiscal_year]
        holders = [n for n in structure.nodes if n.para_range[0] <= p.seq <= n.para_range[1]]
        node = max(holders, key=lambda n: n.level, default=None)
        citations[pid] = Citation(
            paragraph_id=pid,
            fiscal_year=p.fiscal_year,
            page_index=p.page_index,
            page_printed=p.page_printed,
            node_id=node.node_id if node else None,
        )
    return StoryRun(
        run_id=uuid.uuid4().hex,
        ticker=prep.ticker,
        as_of=prep.as_of.isoformat(),
        created_at=datetime.now(UTC).isoformat(),
        years=prep.years,
        filing_ids={str(y): i for y, i in prep.filing_ids.items()},
        rendered=rendered,
        story=story,
        facts=ctx.registry.facts(),
        citations=citations,
        profile=profile,
        change_notes=notes,
        claims={str(y): c for y, c in claims.items()},
        verification=attempts,
        warnings=warnings,
        models={"reader": s.model_for(s.story_reader_role), "writer": s.model_for(s.story_writer_role)},
        prompt_hashes=prompt_hashes(s),
        config_hash=_config_hash_from(s),
        usage=StoryUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=round(usage.cost, 6),
            model_turns=usage.turns,
        ),
    )


def _config_hash_from(settings) -> str:
    keys = sorted(
        k
        for k in type(settings).model_fields
        if k.startswith(("story_", "diff_", "agent_", "model_", "check_"))
    )
    payload = {k: getattr(settings, k) for k in keys} | {"structure_version": STRUCTURE_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def stream_story(prep: PreparedStory, make_model: ModelFactory) -> Iterator[StoryEvent]:
    """Progress events, then ``done`` with the :class:`StoryRun` (or ``error`` with the exception)."""
    events: queue.Queue[StoryEvent | None] = queue.Queue()

    def emit(step: str, message: str, data: dict[str, Any] | None = None) -> None:
        events.put(StoryEvent(type="progress", step=step, message=message, data=data))

    def worker() -> None:
        try:
            years = ", ".join(f"FY{y}" for y in prep.years)
            emit(
                "reports", f"reports selected: {years}", {"years": prep.years, "filing_ids": prep.filing_ids}
            )
            emit(
                "budget",
                f"about {prep.estimated_tokens:,} tokens of report text, {len(prep.change_texts)} change batches",
                {"estimated_tokens": prep.estimated_tokens},
            )
            run = asyncio.run(_build(prep, make_model, emit))
            if prep.store is not None:  # only verified runs get here: a failed run saves nothing
                save_run(prep.store, run)
                emit("saved", f"story run {run.run_id} saved", {"run_id": run.run_id})
            events.put(StoryEvent(type="done", step="done", message="story ready", data=run))
        except Exception as exc:
            events.put(StoryEvent(type="error", step="error", message=str(exc), data=exc))
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, name=f"story-{prep.ticker}", daemon=True)
    thread.start()
    while (event := events.get()) is not None:
        yield event
    thread.join()


# ---------------------------------------------------------------- saved runs


def save_run(store: Store, run: StoryRun) -> None:
    store.save_story_run(run.ticker, run.model_dump(mode="json"))


def latest_run(store: Store, ticker: str) -> StoryRun:
    """The latest saved run, exactly as saved. Raises ``NotCached`` when there is none."""
    data = store.latest_story_run(ticker)
    if data is None:
        raise NotCached(
            f"no saved story for {ticker.upper()}; generate one in live mode (stock-analyzer story {ticker.upper()} --live)"
        )
    return StoryRun.model_validate(data)


def rerender(run: StoryRun) -> RenderedStory:
    """Render a saved story again from the facts saved with it, never from current data, so it
    reads the same after the provider revises a value (company-story spec)."""
    registry = FactRegistry(run.facts)
    story = run.story
    return RenderedStory(
        what_it_does=[render_paragraph(p, registry) for p in story.what_it_does],
        what_changed=[render_paragraph(p, registry) for p in story.what_changed],
        story_vs_numbers=[render_finding(f, registry) for f in story.story_vs_numbers],
        unchanged_sections=run.rendered.unchanged_sections,
    )
