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
    for var in ("FR_API_KEY", "OPENROUTER_API_KEY", "DATA_DIR", "ALLOW_LIVE", "LLM_FAKE", *proxies):
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


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
