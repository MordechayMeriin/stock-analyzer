"""The story's agents: their output schemas, tools and inputs (design D1, D2, D13).

Agents are OpenAI Agents SDK ``Agent`` objects with a pydantic ``output_type``. Their tools are
closures over one :class:`StoryContext` (the run's fact registry, reports and reading budgets),
so every tool call works on this run's data only and reports itself as a progress event.
Tool errors go back to the agent as text, so it can correct itself.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from agents import Agent, function_tool
from agents.models.interface import Model
from pydantic import BaseModel, Field

from stock_analyzer.config import Settings
from stock_analyzer.diff.align import AlignedSection, Comparison
from stock_analyzer.fin.ratios import RATIO_BY_CODE
from stock_analyzer.ingest.parse_md import Paragraph
from stock_analyzer.ingest.structure import Node
from stock_analyzer.story.facts import Fact, FactError, FactRegistry
from stock_analyzer.story.models import Story
from stock_analyzer.story.reading import (
    ReadBudget,
    ReadRefused,
    ReportLibrary,
    label,
    read_paragraphs,
    read_section,
)
from stock_analyzer.story.render import format_fact

ModelFactory = Callable[[str, str], Model]
Emit = Callable[[str, str, dict[str, Any] | None], None]

# ---------------------------------------------------------------- output schemas


class ProfileItem(BaseModel):
    topic: Literal["business_line", "products", "customers", "markets", "scale", "other"]
    text_he: str
    paragraph_ids: list[str]
    fact_ids: list[str] = Field(default_factory=list, description="TXT facts from quote_number, if any")


class CompanyProfile(BaseModel):
    items: list[ProfileItem]


class ChangeNote(BaseModel):
    section_key: str = Field(description="The section key given in the input, e.g. s6.5")
    from_year: int
    to_year: int
    kind: Literal[
        "activity", "customers", "strategy", "risk", "regulation", "organization", "legal", "routine", "other"
    ]
    what_changed_he: str
    old_paragraph_ids: list[str] = Field(default_factory=list)
    new_paragraph_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)


class ChangeNotes(BaseModel):
    notes: list[ChangeNote]


class ManagementClaim(BaseModel):
    topic: str
    line_item_codes: list[str]
    direction: Literal["up", "down", "stable", "mixed", "none"]
    claim_he: str
    paragraph_ids: list[str]
    fact_ids: list[str] = Field(default_factory=list)


class ManagementClaims(BaseModel):
    claims: list[ManagementClaim]


# ---------------------------------------------------------------- run context


@dataclass
class StoryContext:
    settings: Settings
    registry: FactRegistry
    library: ReportLibrary
    years: list[int]  # oldest first
    emit: Emit = lambda step, message, data=None: None
    budgets: dict[str, ReadBudget] = field(default_factory=dict)

    def budget(self, purpose: str) -> ReadBudget:
        if purpose not in self.budgets:
            self.budgets[purpose] = ReadBudget(
                tokens=self.settings.story_reader_budget_tokens, chars_per_token=self.settings.chars_per_token
            )
        return self.budgets[purpose]


def fact_line(f: Fact) -> str:
    conf = "" if f.confidence == "high" else f"  LOW CONFIDENCE ({', '.join(f.failed_checks)})"
    value = format_fact(f) if f.value is not None else f"no value ({f.reason})"
    return f"{{{{{f.fact_id}}}}}  {f.name_he}: {value}{conf}"


# ---------------------------------------------------------------- tools


def reader_tools(ctx: StoryContext, purpose: str) -> list[Any]:
    """quote_number, read_section and read_paragraphs for one agent."""

    @function_tool
    def quote_number(
        paragraph_id: str, text: str, unit: Literal["money", "count", "percent", "number"]
    ) -> str:
        """Register a number that appears in a report paragraph and get its fact token.

        Args:
            paragraph_id: The paragraph id, e.g. MLTM-2025-p0058-003.
            text: The number exactly as written in the paragraph, with its scale word if any (e.g. "1,635 מיליון").
            unit: money, count, percent or number.
        """
        try:
            fact = ctx.registry.quote_number(paragraph_id, text, unit)
        except FactError as exc:
            return f"ERROR: {exc}"
        ctx.emit(
            "tool", f"{purpose}: quote_number → {fact.fact_id}", {"tool": "quote_number", "agent": purpose}
        )
        return f"{{{{{fact.fact_id}}}}} = {format_fact(fact)}"

    @function_tool(name_override="read_section")
    def read_section_tool(fiscal_year: int, node_id: str) -> str:
        """Read one section of a report (charged to your reading budget).

        Args:
            fiscal_year: The report's fiscal year.
            node_id: The section's node id from the outline, e.g. business-7.
        """
        try:
            text = read_section(ctx.library, ctx.budget(purpose), fiscal_year, node_id)
        except ReadRefused as exc:
            return f"ERROR: {exc}"
        ctx.emit(
            "tool",
            f"{purpose}: read_section {fiscal_year} {node_id}",
            {"tool": "read_section", "agent": purpose},
        )
        return text

    @function_tool(name_override="read_paragraphs")
    def read_paragraphs_tool(paragraph_ids: list[str]) -> str:
        """Read report paragraphs by id (charged to your reading budget).

        Args:
            paragraph_ids: Paragraph ids, e.g. ["MLTM-2025-p0058-003"].
        """
        try:
            text = read_paragraphs(ctx.library, ctx.budget(purpose), paragraph_ids)
        except ReadRefused as exc:
            return f"ERROR: {exc}"
        ctx.emit(
            "tool",
            f"{purpose}: read_paragraphs ({len(paragraph_ids)})",
            {"tool": "read_paragraphs", "agent": purpose},
        )
        return text

    return [quote_number, read_section_tool, read_paragraphs_tool]


def writer_tools(ctx: StoryContext, purpose: str) -> list[Any]:
    """The storyteller's tools: the reader tools plus get_facts and derive."""

    @function_tool
    def get_facts(codes: list[str], fiscal_years: list[int]) -> str:
        """Look up facts (values, ratios, changes) by line-item or ratio code.

        Args:
            codes: Line-item or ratio codes, e.g. ["revenue", "gross_margin"]. Empty for every code.
            fiscal_years: Fiscal years to include. Empty for every covered year.
        """
        wanted_years = set(fiscal_years or ctx.years)
        lines = [
            fact_line(f)
            for f in ctx.registry.facts()
            if f.kind in ("FIN", "RATIO", "CHG")
            and (not codes or f.code in codes)
            and wanted_years & set(f.years)
        ]
        ctx.emit(
            "tool",
            f"{purpose}: get_facts {', '.join(codes) or 'all'}",
            {"tool": "get_facts", "agent": purpose},
        )
        if lines:
            return "\n".join(lines[:200])
        known = sorted({f.code for f in ctx.registry.facts() if f.code and f.kind in ("FIN", "RATIO")})
        return "no facts match those codes and years; available codes: " + ", ".join(known)

    @function_tool
    def derive(op: Literal["pct_change", "ratio", "share", "sum", "diff"], fact_ids: list[str]) -> str:
        """Compute a new figure from existing facts and get its fact token.

        Args:
            op: pct_change (from the first fact to the second), ratio (first / second),
                share (first as a share of second), sum, or diff (first minus second).
            fact_ids: Fact ids without braces, e.g. ["FIN:revenue:2024", "FIN:revenue:2025"].
        """
        try:
            fact = ctx.registry.derive(op, fact_ids)
        except FactError as exc:
            return f"ERROR: {exc}"
        ctx.emit("tool", f"{purpose}: derive {op} → {fact.fact_id}", {"tool": "derive", "agent": purpose})
        return fact_line(fact)

    return [*reader_tools(ctx, purpose), get_facts, derive]


# ---------------------------------------------------------------- prompts and agents


def prompt(settings: Settings, name: str) -> str:
    return (Path(settings.prompts_dir) / f"{name}.md").read_text(encoding="utf-8")


def instructions(settings: Settings, name: str) -> str:
    return prompt(settings, name) + "\n\n" + prompt(settings, "story_rules")


def prompt_hashes(settings: Settings) -> dict[str, str]:
    names = ("story_rules", "story_describe", "story_change", "story_explain", "story_storyteller")
    return {n: hashlib.sha256(prompt(settings, n).encode("utf-8")).hexdigest() for n in names}


def describe_agent(ctx: StoryContext, make_model: ModelFactory) -> Agent:
    purpose = "story.describe"
    return Agent(
        name="describe",
        instructions=instructions(ctx.settings, "story_describe"),
        model=make_model(ctx.settings.story_reader_role, purpose),
        tools=reader_tools(ctx, purpose),
        output_type=CompanyProfile,
    )


def change_agent(ctx: StoryContext, make_model: ModelFactory, batch: int) -> Agent:
    purpose = f"story.change.{batch}"
    return Agent(
        name=f"change-{batch}",
        instructions=instructions(ctx.settings, "story_change"),
        model=make_model(ctx.settings.story_reader_role, purpose),
        tools=[reader_tools(ctx, purpose)[0]],  # quote_number only: the texts are in the input
        output_type=ChangeNotes,
    )


def explain_agent(ctx: StoryContext, make_model: ModelFactory, fiscal_year: int) -> Agent:
    purpose = f"story.explain.{fiscal_year}"
    return Agent(
        name=f"explain-{fiscal_year}",
        instructions=instructions(ctx.settings, "story_explain"),
        model=make_model(ctx.settings.story_reader_role, purpose),
        tools=[reader_tools(ctx, purpose)[0]],
        output_type=ManagementClaims,
    )


def storyteller_agent(ctx: StoryContext, make_model: ModelFactory) -> Agent:
    purpose = "story.storyteller"
    return Agent(
        name="storyteller",
        instructions=instructions(ctx.settings, "story_storyteller"),
        model=make_model(ctx.settings.story_writer_role, purpose),
        tools=writer_tools(ctx, purpose),
        output_type=Story,
    )


# ---------------------------------------------------------------- inputs


def _text(paragraphs: list[Paragraph]) -> str:
    return "\n\n".join(label(p) for p in paragraphs)


def describe_input(ctx: StoryContext) -> str:
    """The latest business chapter's outline and its opening sections, up to the intro budget."""
    latest = ctx.years[-1]
    _, structure = ctx.library.reports[latest]
    budget = ReadBudget(
        tokens=ctx.settings.story_describe_intro_tokens, chars_per_token=ctx.settings.chars_per_token
    )
    parts = []
    for node in structure.nodes:
        if node.chapter != "business" or node.kind != "section" or node.level != 2:
            continue
        text = _text(ctx.library.node_paragraphs(latest, node.node_id))
        if budget.estimate(text) > budget.remaining:
            break
        parts.append(budget.charge(text, node.node_id))
    return (
        f"Fiscal year of the latest report: {latest}\n\n"
        f"## Outline of the business-description chapter\n\n{ctx.library.outline(latest, 'business')}\n\n"
        f"## Opening sections\n\n" + "\n\n".join(parts)
    )


def change_units(comparison: Comparison) -> list[tuple[AlignedSection, int, int, str]]:
    """(section, from_year, to_year, status) for every leaf section pair that is not unchanged."""
    parents = {s.parent for s in comparison.sections if s.level == 3}
    leaves = [s for s in comparison.sections if s.level == 3 or s.key not in parents]
    return [(s, p.from_year, p.to_year, p.status) for s in leaves for p in s.pairs if p.status != "unchanged"]


def change_unit_text(
    ctx: StoryContext, unit: tuple[AlignedSection, int, int, str], similarity: float | None
) -> str:
    section, y0, y1, status = unit
    score = f", similarity {similarity:.2f}" if similarity is not None else ""
    out = [f"### {section.title} ({section.key}) FY{y0} → FY{y1}: {status}{score}"]
    for year in (y0, y1):
        node_id = section.node_ids.get(str(year))
        out.append(f"--- FY{year}")
        out.append(_text(ctx.library.node_paragraphs(year, node_id)) if node_id else "(not in this report)")
    return "\n\n".join(out)


def change_batches(ctx: StoryContext, comparison: Comparison) -> list[str]:
    """Changed sections, both full versions each, grouped into batches up to the batch budget."""
    estimate = ReadBudget(tokens=0, chars_per_token=ctx.settings.chars_per_token).estimate
    batches: list[list[str]] = [[]]
    used = 0
    for unit in change_units(comparison):
        pair = next(p for p in unit[0].pairs if (p.from_year, p.to_year) == (unit[1], unit[2]))
        text = change_unit_text(ctx, unit, pair.similarity)
        cost = estimate(text)
        if batches[-1] and used + cost > ctx.settings.story_change_batch_tokens:
            batches.append([])
            used = 0
        batches[-1].append(text)
        used += cost
    return ["\n\n".join(b) for b in batches if b]


def directors_explanations(ctx: StoryContext, fiscal_year: int) -> list[Paragraph]:
    """The part of the directors' report that explains the business and results (part A)."""
    _, structure = ctx.library.reports[fiscal_year]
    nodes: list[Node] = [n for n in structure.nodes if n.chapter == "directors"]
    part = next((n for n in nodes if n.level == 2 and "הסברי הדירקטוריון" in n.title), None)
    target = part or next((n for n in nodes if n.kind == "chapter"), None)
    return ctx.library.node_paragraphs(fiscal_year, target.node_id) if target else []


def explain_input(ctx: StoryContext, fiscal_year: int) -> str | None:
    paragraphs = directors_explanations(ctx, fiscal_year)
    if not paragraphs:
        return None
    return f"Fiscal year: {fiscal_year}\n\n## Directors' report: explanations of the results\n\n{_text(paragraphs)}"


# canonical sheet fields (fin/canonical.py)
CORE_FIN_CODES = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income_parent",
    "cfo",
    "capex",
    "total_assets",
    "total_equity",
    "total_debt",
    "net_debt",
)


def facts_table(ctx: StoryContext) -> str:
    """Core values, every core ratio, and their year-over-year changes, one line per fact."""
    core = set(CORE_FIN_CODES) | set(RATIO_BY_CODE)
    rows = [
        fact_line(f)
        for f in ctx.registry.facts()
        if (f.kind == "FIN" and f.code in CORE_FIN_CODES)
        or f.kind == "RATIO"
        or (f.kind == "CHG" and f.code in core)
    ]
    return "\n".join(rows)


def storyteller_input(
    ctx: StoryContext,
    profile: CompanyProfile | None,
    notes: list[ChangeNote],
    claims: dict[int, list[ManagementClaim]],
    unchanged: list[AlignedSection],
) -> str:
    years = ", ".join(str(y) for y in ctx.years)
    parts = [f"Covered fiscal years: {years}"]
    if profile:
        parts.append("## Company profile (latest report)\n\n" + profile.model_dump_json(indent=1))
    parts.append(
        "## What changed in the business description\n\n" + ChangeNotes(notes=notes).model_dump_json(indent=1)
    )
    for fy in ctx.years:
        parts.append(
            f"## Management's explanations, FY{fy}\n\n"
            + ManagementClaims(claims=claims.get(fy, [])).model_dump_json(indent=1)
        )
    parts.append(
        "## Business sections unchanged across the years\n\n" + "\n".join(f"- {s.title}" for s in unchanged)
    )
    parts.append("## Core financial facts\n\n" + facts_table(ctx))
    return "\n\n".join(parts)
