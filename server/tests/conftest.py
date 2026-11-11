"""Shared fixtures. Every test runs offline: real sockets are blocked and credentials cleared.

HTTP is mocked with respx (it intercepts httpx at the transport layer, below which nothing
reaches a socket), and FastAPI's TestClient runs in-process.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from pydantic import SecretStr

from stock_analyzer.config import Settings, reset_settings_cache
from stock_analyzer.ingest.fr_client import read_exact

FIXTURES = Path(__file__).parent / "fixtures"
SERVER_ROOT = Path(__file__).resolve().parent.parent


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    real_connect = socket.socket.connect

    def guarded(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise NetworkBlocked(f"network access attempted in tests: {address!r}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    proxies = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
    cleared = ("FR_API_KEY", "OPENROUTER_API_KEY", "DATABASE_URL", "TEST_DATABASE_URL", "DATA_DIR")
    for var in (*cleared, "ALLOW_LIVE", "LLM_FAKE", *proxies):
        monkeypatch.delenv(var, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def data_dir(tmp_path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def settings(data_dir) -> Settings:
    """Settings for unit tests: temp data dir, dummy keys, instant backoff."""
    return Settings(
        data_dir=data_dir,
        companies_file=SERVER_ROOT / "data" / "companies.yaml",
        prompts_dir=SERVER_ROOT / "prompts",
        fr_api_key=SecretStr("test-fr-key-DO-NOT-LOG"),
        openrouter_api_key=SecretStr("test-or-key-DO-NOT-LOG"),
        fr_backoff_base_s=0.0,
        fr_backoff_max_s=0.0,
    )


STORE_BACKENDS = ["fs"]


@pytest.fixture(params=STORE_BACKENDS)
def store(request, settings):
    """A state store on each backend under test, empty at the start of the test."""
    from stock_analyzer.store import FsStore

    s = FsStore(settings)
    yield s
    s.close()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


LIVE_RAW = SERVER_ROOT / "data" / "raw" / "MLTM"
LIVE_FILINGS = {2024: 63741657, 2025: 32935334}


def live_report(fiscal_year: int) -> str:
    """Full cached Malam report text; skips the test when it has not been fetched."""
    path = LIVE_RAW / f"{fiscal_year}.md"
    if not path.exists():
        pytest.skip(
            f"full Malam FY{fiscal_year} report not cached (run: stock-analyzer fetch MLTM {fiscal_year})"
        )
    return read_exact(path)


def fixture_text(name: str) -> str:
    return read_exact(FIXTURES / name)


def seed_fr_cache(settings, path: str, params: dict, body) -> None:
    """Put a provider response into the FR client's disk cache (as if fetched live)."""
    import json as _json
    from datetime import UTC, datetime

    from stock_analyzer.ingest.fr_client import FRClient, FRResponse

    client = FRClient(settings)
    text = body if isinstance(body, str) else _json.dumps(body, ensure_ascii=False)
    client.cache.set(
        FRClient.cache_key(path, params),
        FRResponse(
            status=200, body=text, total_chars=len(text), fetched_at=datetime.now(UTC).isoformat()
        ).model_dump(),
    )
    client.close()


def seed_malam(settings) -> None:
    """Cached Malam data for offline service/API tests: filings, FY2025 report (fixture), financials."""
    import json as _json

    from stock_analyzer.ingest.fr_client import Filing, save_report

    filings = _json.loads((FIXTURES / "malam_filings.json").read_text())
    seed_fr_cache(
        settings,
        "/filings/",
        {
            "company": 6901,
            "type": "10-K",
            "ordering": "-release_datetime",
            "view": "full",
            "page_size": 100,
            "page": 1,
        },
        filings,
    )
    seed_fr_cache(
        settings,
        "/companies/6901/financials/",
        {"fiscal_period": "FY"},
        _json.loads((FIXTURES / "mltm_financials.json").read_text()),
    )
    row = next(r for r in filings["results"] if r["id"] == 32935334)
    save_report(settings, "MLTM", 2025, Filing.model_validate(row), fixture_text("mltm_2025_style_b.md"))
