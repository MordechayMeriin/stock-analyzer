"""Shared fixtures. Every test runs offline: real sockets are blocked and credentials cleared.

HTTP is mocked with respx (it intercepts httpx at the transport layer, below which nothing
reaches a socket), and FastAPI's TestClient runs in-process.
"""

from __future__ import annotations

import os
import socket
import uuid
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


# Read before the autouse fixture clears it. When set, the store contract also runs on Postgres
# (design D10). psycopg connects through libpq's own sockets, which the Python-level guard above
# cannot see, so Postgres tests only ever run against this explicitly configured database.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip() or None
STORE_BACKENDS = [
    "fs",
    pytest.param(
        "postgres",
        marks=pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not set"),
    ),
]


@pytest.fixture
def pg_schema():
    """A fresh, empty schema with the state-store tables, dropped after the test."""
    import psycopg

    from stock_analyzer.store.pg import PgStore

    schema = f"sa_test_{uuid.uuid4().hex[:12]}"
    store = PgStore(TEST_DATABASE_URL, schema=schema)
    store.init_schema()
    yield store
    store.shutdown()
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f'drop schema if exists "{schema}" cascade')


@pytest.fixture(params=STORE_BACKENDS)
def store(request, settings):
    """A state store on each backend under test, empty at the start of the test."""
    if request.param == "postgres":
        yield request.getfixturevalue("pg_schema")
        return
    from stock_analyzer.store import FsStore

    s = FsStore(settings)
    yield s
    s.close()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


# Full stored reports for the opt-in ``live_data`` tests, read through the state store
# (design D12): the local ``DATA_DIR`` (default ``server/data``) or, when ``DATABASE_URL`` is set,
# the Postgres store it names (e.g. the hosted one, which holds every reference report, so these
# tests cost no provider credits). Both are read here, before the autouse fixture clears them.
LIVE_DATA_DIR = Path(os.environ.get("DATA_DIR", "").strip() or SERVER_ROOT / "data")
LIVE_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip() or None

# The reference reports every parser change is checked against (report-parsing spec).
REFERENCE_REPORTS: list[tuple[str, int]] = [
    ("MLTM", 2024),
    ("MLTM", 2025),
    ("ELAL", 2024),
    ("ELAL", 2025),
    ("RMLI", 2025),
    ("DLEKG", 2025),
]

_live_store = None


def _get_live_store():
    global _live_store
    if _live_store is None:
        import atexit

        from stock_analyzer.store import get_store

        live_settings = Settings(
            data_dir=LIVE_DATA_DIR,
            database_url=SecretStr(LIVE_DATABASE_URL) if LIVE_DATABASE_URL else None,
        )
        _live_store = get_store(live_settings)
        atexit.register(_live_store.close)
    return _live_store


def live_report(ticker: str, fiscal_year: int) -> tuple[str, int]:
    """(text, filing id) of a full stored report; skips the test when it is not stored."""
    loaded = _get_live_store().load_report(ticker.upper(), fiscal_year)
    if loaded is None:
        where = "the DATABASE_URL store" if LIVE_DATABASE_URL else str(LIVE_DATA_DIR)
        pytest.skip(
            f"full {ticker.upper()} FY{fiscal_year} report not stored in {where} "
            f"(run: stock-analyzer fetch {ticker.upper()} {fiscal_year})"
        )
    text, meta = loaded
    return text, meta.filing_id


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


def seed_financials(settings, ticker: str, fr_company_id: int, fixture: str, name_he: str) -> None:
    """Track a company (runtime-added) and cache its financials fixture, as if fetched live."""
    import json as _json

    from stock_analyzer.companies import TrackedCompany
    from stock_analyzer.store import get_store

    store = get_store(settings)
    store.add_tracked(TrackedCompany(ticker=ticker, fr_company_id=fr_company_id, name_he=name_he))
    store.close()
    seed_fr_cache(
        settings,
        f"/companies/{fr_company_id}/financials/",
        {"fiscal_period": "FY"},
        _json.loads((FIXTURES / fixture).read_text()),
    )


def seed_bank_and_insurer(settings) -> None:
    """Cached financials for Leumi (template bank) and Harel (template insurer)."""
    seed_financials(settings, "LUMI", 6889, "lumi_financials.json", "בנק לאומי")
    seed_financials(settings, "HARL", 6832, "harl_financials.json", "הראל השקעות")
