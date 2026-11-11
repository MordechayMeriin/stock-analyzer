"""FastAPI application (analyzer-api spec). Run: ``uvicorn stock_analyzer.api.main:app``."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stock_analyzer import __version__
from stock_analyzer.api import errors
from stock_analyzer.api.routers import companies, playground, reports, usage
from stock_analyzer.api.schemas import HealthOut, StorageHealth
from stock_analyzer.config import Settings, get_settings
from stock_analyzer.store import get_store


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="The Committee — Analyzer API",
        version=__version__,
        description="Hebrew year-over-year analysis of Israeli periodic reports. Every endpoint calls the same "
        "service functions as the CLI. Data routes take `mode=cached|live`.",
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept", "Cache-Control"],
    )
    errors.install(app)

    @app.get("/health", response_model=HealthOut, tags=["health"], summary="Liveness and configuration flags")
    def health() -> HealthOut:
        # Always 200: a paused database shows as storage.ok=false instead of failing the host's
        # health check, which would only restart the service in a loop (design D6).
        s: Settings = app.state.settings
        store = get_store(s)
        try:
            storage = StorageHealth(backend=store.backend, ok=store.ping())
        finally:
            store.close()
        return HealthOut(
            version=__version__,
            allow_live=s.allow_live,
            llm_fake=s.llm_fake,
            credentials=s.credential_flags(),
            models={"main": s.model_main, "cheap": s.model_cheap},
            storage=storage,
        )

    for module in (companies, reports, usage, playground):
        app.include_router(module.router)
    return app


def __getattr__(name: str):  # lazy module-level app so importing never reads env eagerly
    if name == "app":
        return create_app()
    raise AttributeError(name)
