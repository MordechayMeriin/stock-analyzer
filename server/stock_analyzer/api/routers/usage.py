from __future__ import annotations

from fastapi import APIRouter

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.services import usage
from stock_analyzer.services.models import UsageOut

router = APIRouter(prefix="/api", tags=["usage"])


@router.get("/usage", response_model=UsageOut, summary="Provider credits and LLM spend")
def get_usage(ctx: CtxDep) -> UsageOut:
    return usage.usage(ctx)
