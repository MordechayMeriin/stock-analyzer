from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.services import reports
from stock_analyzer.services.models import NodeParagraphsOut, PageParagraphsOut, StructureOut

router = APIRouter(prefix="/api/companies/{ticker}/reports/{fiscal_year}", tags=["reports"])

FiscalYear = Annotated[int, Path(ge=1990, le=2100)]


@router.get("/structure", response_model=StructureOut, summary="Report structure tree")
def get_structure(ctx: CtxDep, ticker: str, fiscal_year: FiscalYear) -> StructureOut:
    return reports.report_structure(ctx, ticker, fiscal_year)


@router.get("/nodes/{node_id}", response_model=NodeParagraphsOut, summary="Paragraphs of a structure node")
def get_node(ctx: CtxDep, ticker: str, fiscal_year: FiscalYear, node_id: str) -> NodeParagraphsOut:
    return reports.node_paragraphs(ctx, ticker, fiscal_year, node_id)


@router.get(
    "/pages/{page_index}", response_model=PageParagraphsOut, summary="Paragraphs of a page (PDF page index)"
)
def get_page(
    ctx: CtxDep, ticker: str, fiscal_year: FiscalYear, page_index: Annotated[int, Path(ge=1)]
) -> PageParagraphsOut:
    return reports.page_paragraphs(ctx, ticker, fiscal_year, page_index)
