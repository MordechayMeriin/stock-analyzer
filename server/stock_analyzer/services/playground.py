"""LLM playground: the selected report text plus a question → the main model, streamed (design D7)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

from stock_analyzer.errors import LiveModeDisabled, SelectionTooLarge
from stock_analyzer.llm import LLM, DoneEvent, FakeLLM, StreamEvent, get_llm
from stock_analyzer.services import reports
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import ParagraphOut


@dataclass
class PreparedQuestion:
    system: str
    user: str
    paragraphs: list[ParagraphOut]
    estimated_tokens: int


def estimate_tokens(text: str, chars_per_token: float) -> int:
    return math.ceil(len(text) / max(chars_per_token, 0.1))


def label(p: ParagraphOut) -> str:
    page = f"עמ' {p.page_printed}" if p.page_printed is not None else f"עמוד {p.page_index} בקובץ"
    return f"[{p.pid}] ({page})\n{p.text}"


def prepare(
    ctx: Ctx,
    ticker: str,
    fiscal_year: int,
    question: str,
    *,
    node_id: str | None = None,
    pages: tuple[int, int] | None = None,
) -> PreparedQuestion:
    paragraphs = reports.select_paragraphs(ctx, ticker, fiscal_year, node_id=node_id, pages=pages)
    excerpts = "\n\n".join(label(p) for p in paragraphs)
    tokens = estimate_tokens(excerpts, ctx.settings.chars_per_token)
    if tokens > ctx.settings.playground_max_tokens:
        raise SelectionTooLarge(
            f"the selected text is about {tokens:,} tokens, over the {ctx.settings.playground_max_tokens:,}-token "
            "limit; select a narrower section or fewer pages"
        )
    system = (ctx.settings.prompts_dir / "playground.md").read_text(encoding="utf-8")
    user = f"קטעים מהדוח:\n\n{excerpts}\n\n---\nשאלה: {question.strip()}"
    return PreparedQuestion(system=system, user=user, paragraphs=paragraphs, estimated_tokens=tokens)


def resolve_llm(ctx: Ctx, override: LLM | None = None) -> LLM:
    """The LLM for a playground call. Paid calls need live mode: cached mode spends nothing."""
    if override is not None:
        return override
    llm = get_llm(ctx.settings, store=ctx.store)
    if not isinstance(llm, FakeLLM) and ctx.mode != "live":
        raise LiveModeDisabled(
            "the playground calls the LLM, which costs money: switch to live mode (or run with LLM_FAKE=true)"
        )
    return llm


def stream(llm: LLM, prepared: PreparedQuestion) -> Iterator[StreamEvent]:
    yield from llm.stream_text("main", prepared.system, prepared.user, purpose="playground")


def citations(prepared: PreparedQuestion) -> dict[str, str | None]:
    return {p.pid: p.citation_url for p in prepared.paragraphs}


__all__ = [
    "PreparedQuestion",
    "prepare",
    "resolve_llm",
    "stream",
    "citations",
    "DoneEvent",
    "estimate_tokens",
]
