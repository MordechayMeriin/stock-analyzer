"""The API on the Postgres state store: same answers as on files, clean storage errors.

Runs only when ``TEST_DATABASE_URL`` is set (see ``conftest.py``).
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from stock_analyzer.api.main import create_app
from stock_analyzer.store.pg import PgStore
from tests.conftest import TEST_DATABASE_URL, seed_fr_cache, seed_malam

pytestmark = pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not set")

STORE_USERS = (
    "stock_analyzer.services.context",
    "stock_analyzer.ingest.fr_client",
    "stock_analyzer.llm",
    "stock_analyzer.api.main",
)


def use_store(monkeypatch, store) -> None:
    """Make every get_store() call in the app return ``store`` (as DATABASE_URL would)."""
    for module in STORE_USERS:
        monkeypatch.setattr(f"{module}.get_store", lambda settings, **_: store)


@pytest.fixture
def pg_client(monkeypatch, settings, pg_schema):
    use_store(monkeypatch, pg_schema)
    seed_malam(settings)  # written to Postgres, not DATA_DIR
    with TestClient(create_app(settings)) as c:
        yield c


def test_cached_reads_come_from_postgres(pg_client, settings, pg_schema):
    assert not (settings.data_dir / "raw").exists()  # nothing on disk
    assert pg_schema.cached_filing_id("MLTM", 2025) == 32935334
    years = pg_client.get("/api/companies/MLTM/filings").json()["years"]
    fy2025 = next(y for y in years if y["fiscal_year"] == 2025)
    assert fy2025["report_cached"] is True and fy2025["selected_filing_id"] == 32935334
    structure = pg_client.get("/api/companies/MLTM/reports/2025/structure").json()
    assert structure["page_count"] == 36
    fin = pg_client.get("/api/companies/MLTM/financials").json()
    assert fin["currency"] == "ILS" and fin["years"][0] == 2025


def test_usage_totals_from_postgres_log(pg_client, settings, pg_schema):
    seed_fr_cache(settings, "/usage/", {}, {"free_credits": {"remaining": 224}})
    pg_schema.log("llm", {"cost": 0.25, "cache_hit": False, "ok": True})
    body = pg_client.get("/api/usage").json()
    assert body["provider"]["free_credits"]["remaining"] == 224
    assert body["llm"]["total_cost_usd"] == 0.25
    assert body["fr_log"] == {"calls": 1, "cache_hits": 1, "network_calls": 0, "credits_logged": 0}


def test_health_reports_postgres_reachable(pg_client):
    body = pg_client.get("/health").json()
    assert body["storage"] == {"backend": "postgres", "ok": True}
    assert TEST_DATABASE_URL not in pg_client.get("/health").text


def test_missing_schema_is_a_configuration_error(monkeypatch, settings):
    schema = f"sa_test_{uuid.uuid4().hex[:12]}"
    use_store(monkeypatch, PgStore(TEST_DATABASE_URL, schema=schema))
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/companies/MLTM/filings")
    assert r.status_code == 503
    assert r.json()["code"] == "configuration_error"
    assert "stock-analyzer db init" in r.json()["message"]
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        assert conn.execute("select to_regnamespace(%s)", (schema,)).fetchone()[0] is None


def test_unreachable_database_is_storage_unavailable(monkeypatch, settings):
    url = "postgresql://secret_user:secret_pw@127.0.0.1:1/secret_db"
    use_store(monkeypatch, PgStore(url, connect_timeout=2))
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/companies/MLTM/filings")
        health = c.get("/health")
    assert r.status_code == 503 and r.json()["code"] == "storage_unavailable"
    # health still answers 200 and reports storage as down
    assert health.status_code == 200 and health.json()["status"] == "ok"
    assert health.json()["storage"] == {"backend": "postgres", "ok": False}
    for leak in ("secret_user", "secret_pw", "secret_db", "127.0.0.1"):
        assert leak not in r.text and leak not in health.text
