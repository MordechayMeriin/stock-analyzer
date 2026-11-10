"""Request dependencies: settings from the app, and a per-request service context (mode)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import Depends, Query, Request

from stock_analyzer.config import Settings
from stock_analyzer.services.context import Ctx

ModeParam = Annotated[
    Literal["cached", "live"],
    Query(
        description="cached: local data only, no provider calls. live: fetch what is missing (if the server allows)."
    ),
]


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_ctx(request: Request, mode: ModeParam = "cached") -> Iterator[Ctx]:
    ctx = Ctx(request.app.state.settings, mode=mode)
    try:
        yield ctx
    finally:
        ctx.close()


CtxDep = Annotated[Ctx, Depends(get_ctx)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
