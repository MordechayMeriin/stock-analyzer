"""Company report endpoints: the five-axis report built from the latest story run (company-report spec)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.report.models import AxisDetail, CompanyReport
from stock_analyzer.services import report

router = APIRouter(prefix="/api/companies", tags=["report"])


@router.get(
    "/{ticker}/report",
    response_model=CompanyReport,
    summary="The company report (cached: the saved one; live: build it from the latest story when missing)",
)
def get_report(ctx: CtxDep, ticker: str) -> CompanyReport:
    return report.get_report(ctx, ticker)


@router.get(
    "/{ticker}/report/axes/{axis_id}",
    response_model=AxisDetail,
    summary="One axis's breakdown for a fiscal year, from the saved report",
)
def get_axis_detail(ctx: CtxDep, ticker: str, axis_id: str, year: int = Query(...)) -> AxisDetail:
    return report.get_axis_detail(ctx, ticker, axis_id, year)
