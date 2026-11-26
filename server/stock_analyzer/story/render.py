"""Rendering: fact tokens become formatted values, so web and CLI never format numbers (design D3).

A rendered paragraph is a list of segments: plain text, a fact (its id and display string), or a
caveat that code writes from the failed data-quality checks of the facts the LLM declared.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel

from stock_analyzer.story.facts import Fact, FactRegistry
from stock_analyzer.story.models import Finding, StoryParagraph
from stock_analyzer.story.verify import TOKEN

CURRENCY_SYMBOLS = {"ILS": "₪", "USD": "$", "EUR": "€", "GBP": "£"}
MILLION = Decimal(1_000_000)


class Segment(BaseModel):
    type: Literal["text", "fact", "caveat"]
    text: str | None = None  # text and caveat segments
    fact_id: str | None = None  # fact segments
    display: str | None = None  # fact segments: the formatted value
    fact_ids: list[str] = []  # caveat segments: the facts it is about


class RenderedParagraph(BaseModel):
    segments: list[Segment]
    paragraph_ids: list[str]


class RenderedFinding(RenderedParagraph):
    label: Literal["consistent", "tension", "unexplained"]
    fact_ids: list[str]


def _q(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _signed(text: str, value: Decimal) -> str:
    return f"+{text}" if value > 0 else text


def format_fact(fact: Fact) -> str:
    """The display string of a fact, e.g. ``4,138 מיליון ₪``, ``10.47%``, ``−0.13 נ"א``."""
    v = fact.decimal
    if v is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get(fact.currency or "", fact.currency or "")
    money_suffix = f" {symbol}" if symbol else ""
    change = fact.kind == "CHG" or fact.operation == "pct_change"
    if fact.unit == "money":
        if abs(v) >= 100 * MILLION:
            return f"{_q(v / MILLION, 0):,} מיליון{money_suffix}"
        if abs(v) >= MILLION:
            return f"{_q(v / MILLION, 1):,} מיליון{money_suffix}"
        return f"{_q(v, 0):,}{money_suffix}"
    if fact.unit == "percent":
        text = f"{_q(v * 100, 2)}%"
        return _signed(text, v) if change else text
    if fact.unit == "pp":
        return _signed(f'{_q(v * 100, 2)} נ"א', v)
    if fact.unit == "multiple":
        text = f"{_q(v, 2)}"
        return _signed(text, v) if change else text
    if fact.unit == "days":
        return _signed(f"{_q(v, 0)} ימים", v) if change else f"{_q(v, 0)} ימים"
    if fact.unit == "per_share":
        return f"{_q(v, 2)}{money_suffix}"
    if fact.unit == "count":
        return f"{_q(v, 0):,}"
    return f"{v.normalize():,}" if v == v.to_integral_value() else f"{v}"


def caveat_text(facts: list[Fact]) -> str:
    parts = []
    for f in facts:
        checks = ", ".join(f.failed_checks) or "בדיקות איכות נתונים"
        parts.append(f"{f.name_he} ({checks})")
    return "נתונים בביטחון נמוך, כי נכשלו בדיקות עקביות בנתוני הספק: " + "; ".join(parts)


def render_text(text: str, registry: FactRegistry) -> list[Segment]:
    segments: list[Segment] = []
    pos = 0
    for m in TOKEN.finditer(text):
        if m.start() > pos:
            segments.append(Segment(type="text", text=text[pos : m.start()]))
        fact = registry.get(m.group(1))
        segments.append(Segment(type="fact", fact_id=fact.fact_id, display=format_fact(fact)))
        pos = m.end()
    if pos < len(text):
        segments.append(Segment(type="text", text=text[pos:]))
    return segments


def _caveat(item: StoryParagraph | Finding, registry: FactRegistry) -> list[Segment]:
    facts = [registry.get(i) for i in dict.fromkeys(item.caveat_fact_ids) if i in registry]
    if not facts:
        return []
    return [Segment(type="caveat", text=caveat_text(facts), fact_ids=[f.fact_id for f in facts])]


def render_paragraph(p: StoryParagraph, registry: FactRegistry) -> RenderedParagraph:
    return RenderedParagraph(
        segments=render_text(p.text_he, registry) + _caveat(p, registry), paragraph_ids=list(p.paragraph_ids)
    )


def render_finding(f: Finding, registry: FactRegistry) -> RenderedFinding:
    return RenderedFinding(
        label=f.label,
        segments=render_text(f.text_he, registry) + _caveat(f, registry),
        paragraph_ids=list(f.paragraph_ids),
        fact_ids=list(f.fact_ids),
    )
