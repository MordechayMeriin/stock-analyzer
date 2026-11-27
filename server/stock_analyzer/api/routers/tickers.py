from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from stock_analyzer.api.deps import CtxDep
from stock_analyzer.services import tickers
from stock_analyzer.services.models import TickerSearchOut

router = APIRouter(prefix="/api/tickers", tags=["tickers"])


@router.get(
    "",
    response_model=TickerSearchOut,
    summary="Ticker autocomplete (free, cached-only)",
    description="Searches the stored directory of TASE-listed companies plus the tracked companies. Free: it "
    "reads stored data only and never calls the provider, even with `mode=live`, so the client may call it on "
    "every keystroke. Without a stored directory only tracked companies are found (`directory.source` is "
    "`tracked_only`). The directory is filled by `stock-analyzer companies directory --refresh` (CLI, spends credits).",
)
def search_tickers(
    ctx: CtxDep,
    q: Annotated[str, Query(min_length=1, max_length=60, description="Ticker or name text")],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> TickerSearchOut:
    return tickers.search(ctx, q, limit)
