"""Report services: structure tree, node paragraphs and page paragraphs with citations.

Parsed structures are recomputed from the raw Markdown (cheap, deterministic) and memoized
on (file hash, parser version, structure version) so the API does not reparse per request.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

from stock_analyzer.companies import resolve_ticker
from stock_analyzer.errors import NodeNotFound, NotCached, PageNotFound
from stock_analyzer.ingest.fr_client import ReportMeta, load_report, save_report
from stock_analyzer.ingest.parse_md import PARSER_VERSION, Paragraph, ParsedReport, parse_report
from stock_analyzer.ingest.select import select_report
from stock_analyzer.ingest.structure import STRUCTURE_VERSION, Node, Structure, build_structure
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import (
    NodeOut,
    NodeParagraphsOut,
    PageParagraphsOut,
    ParagraphOut,
    StructureOut,
    TocEntryOut,
)

_MEMO: OrderedDict[str, tuple[ParsedReport, Structure, ReportMeta]] = OrderedDict()
_MEMO_LOCK = threading.Lock()
_MEMO_SIZE = 8


def citation_url(document_url: str | None, page_index: int) -> str | None:
    return f"{document_url}#page={page_index}" if document_url else None


def _ensure_raw(ctx: Ctx, ticker: str, fiscal_year: int) -> tuple[str, ReportMeta]:
    loaded = load_report(ctx.settings, ticker, fiscal_year)
    if loaded is not None and not ctx.refresh:
        return loaded
    if ctx.mode != "live":
        raise NotCached(
            f"report {ticker.upper()} FY{fiscal_year} is not cached; fetch it in live mode "
            f"(stock-analyzer fetch {ticker.upper()} {fiscal_year})"
        )
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    filing = select_report(ctx.fr.list_filings(company.fr_company_id), fiscal_year, ticker=company.ticker)
    text = ctx.fr.get_markdown(filing.id)
    meta = save_report(ctx.settings, company.ticker, fiscal_year, filing, text)
    return text, meta


def load_parsed(ctx: Ctx, ticker: str, fiscal_year: int) -> tuple[ParsedReport, Structure, ReportMeta]:
    company = resolve_ticker(ctx.settings.companies_file, ticker)
    text, meta = _ensure_raw(ctx, company.ticker, fiscal_year)
    key = "|".join(
        [
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            PARSER_VERSION,
            STRUCTURE_VERSION,
            company.ticker,
            str(fiscal_year),
        ]
    )
    with _MEMO_LOCK:
        if key in _MEMO:
            _MEMO.move_to_end(key)
            return _MEMO[key]
    parsed = parse_report(
        text, ticker=company.ticker, fiscal_year=fiscal_year, filing_id=meta.filing_id, settings=ctx.settings
    )
    structure = build_structure(parsed, ctx.settings)
    with _MEMO_LOCK:
        _MEMO[key] = (parsed, structure, meta)
        while len(_MEMO) > _MEMO_SIZE:
            _MEMO.popitem(last=False)
    return parsed, structure, meta


def _printed(parsed: ParsedReport, page_index: int) -> int | None:
    return next((p.printed for p in parsed.pages if p.index == page_index), None)


def _node_out(node: Node, parsed: ParsedReport) -> NodeOut:
    return NodeOut(
        node_id=node.node_id,
        kind=node.kind,
        chapter=node.chapter,
        number=node.number,
        title=node.title,
        level=node.level,
        para_range=node.para_range,
        pages=node.pages,
        printed_pages=(_printed(parsed, node.pages[0]), _printed(parsed, node.pages[1])),
        children=node.children,
        parent=node.parent,
    )


def _para_out(p: Paragraph, document_url: str | None) -> ParagraphOut:
    return ParagraphOut(
        pid=p.pid,
        seq=p.seq,
        text=p.text,
        page_index=p.page_index,
        page_printed=p.page_printed,
        heading_level=p.heading_level,
        in_table=p.in_table,
        citation_url=citation_url(document_url, p.page_index),
    )


def report_structure(ctx: Ctx, ticker: str, fiscal_year: int) -> StructureOut:
    parsed, structure, meta = load_parsed(ctx, ticker, fiscal_year)
    return StructureOut(
        ticker=structure.ticker,
        fiscal_year=fiscal_year,
        filing_id=meta.filing_id,
        document_url=meta.document_url,
        page_count=parsed.page_count,
        page_style=parsed.style,
        nodes=[_node_out(n, parsed) for n in structure.nodes],
        roots=structure.roots,
        toc=[TocEntryOut(**e.model_dump()) for e in structure.toc],
        coverage=structure.coverage,
        warnings=structure.warnings + parsed.warnings,
    )


def node_paragraphs(ctx: Ctx, ticker: str, fiscal_year: int, node_id: str) -> NodeParagraphsOut:
    parsed, structure, meta = load_parsed(ctx, ticker, fiscal_year)
    node = structure.node(node_id)
    if node is None:
        raise NodeNotFound(f"no node {node_id!r} in {structure.ticker} FY{fiscal_year}")
    a, b = node.para_range
    return NodeParagraphsOut(
        ticker=structure.ticker,
        fiscal_year=fiscal_year,
        node=_node_out(node, parsed),
        paragraphs=[_para_out(p, meta.document_url) for p in parsed.paragraphs[a : b + 1]],
    )


def page_paragraphs(ctx: Ctx, ticker: str, fiscal_year: int, page_index: int) -> PageParagraphsOut:
    parsed, structure, meta = load_parsed(ctx, ticker, fiscal_year)
    if not any(p.index == page_index for p in parsed.pages):
        raise PageNotFound(
            f"page {page_index} is outside {structure.ticker} FY{fiscal_year} (1-{parsed.page_count})"
        )
    paras = [p for p in parsed.paragraphs if p.page_index == page_index]
    covering = [n for n in structure.nodes if n.pages[0] <= page_index <= n.pages[1]]
    deepest = [n.node_id for n in covering if not any(c in {x.node_id for x in covering} for c in n.children)]
    return PageParagraphsOut(
        ticker=structure.ticker,
        fiscal_year=fiscal_year,
        page_index=page_index,
        page_printed=_printed(parsed, page_index),
        citation_url=citation_url(meta.document_url, page_index),
        node_ids=deepest,
        paragraphs=[_para_out(p, meta.document_url) for p in paras],
    )


def select_paragraphs(
    ctx: Ctx,
    ticker: str,
    fiscal_year: int,
    *,
    node_id: str | None = None,
    pages: tuple[int, int] | None = None,
) -> list[ParagraphOut]:
    """Paragraphs of a node or an inclusive page range (used by the playground)."""
    parsed, structure, meta = load_parsed(ctx, ticker, fiscal_year)
    if node_id is not None:
        return node_paragraphs(ctx, ticker, fiscal_year, node_id).paragraphs
    if pages is None:
        raise ValueError("select a node or a page range")
    first, last = pages
    if (
        first > last
        or not any(p.index == first for p in parsed.pages)
        or not any(p.index == last for p in parsed.pages)
    ):
        raise PageNotFound(
            f"page range {first}-{last} is outside {structure.ticker} FY{fiscal_year} (1-{parsed.page_count})"
        )
    return [_para_out(p, meta.document_url) for p in parsed.paragraphs if first <= p.page_index <= last]
