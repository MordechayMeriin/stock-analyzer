"""State store contract: the same behaviour on every backend (state-store spec, design D10).

Each test runs against the file backend, and against Postgres when ``TEST_DATABASE_URL``
is set (see the ``store`` fixture in ``conftest.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from stock_analyzer.errors import NotCached
from stock_analyzer.ingest.fr_client import FRClient
from stock_analyzer.store import ReportMeta, fr_totals, llm_totals

BASE = "https://api.financialreports.eu"
HEBREW_CRLF = "# דוח תקופתי לשנת 2025\r\nפרק א׳ – תיאור עסקי התאגיד\r\n\r\n| ש״ח | 1,234 |\n‏סוף\n"


def _meta(filing_id: int = 32935334, text: str = HEBREW_CRLF) -> ReportMeta:
    return ReportMeta(
        ticker="MLTM",
        fiscal_year=2025,
        filing_id=filing_id,
        title="דוח תקופתי 2025",
        document_url="https://example.test/32935334.pdf",
        release_datetime=datetime(2026, 3, 30, 18, 0, tzinfo=UTC),
        total_chars=len(text),
        sha256="0" * 64,
        fetched_at="2026-11-11T10:00:00+00:00",
    )


def test_cache_get_set_contains_per_namespace(store):
    fr, llm = store.cache("fr"), store.cache("llm")
    assert fr.get("k") is None and "k" not in fr
    fr.set("k", {"status": 200, "body": "גוף", "total_chars": 3, "next_offset": None})
    llm.set("k", '{"verdict": "א"}')
    assert "k" in fr and "k" in llm
    assert fr.get("k") == {"status": 200, "body": "גוף", "total_chars": 3, "next_offset": None}
    assert llm.get("k") == '{"verdict": "א"}'
    assert "other" not in fr


def test_cache_overwrite_and_delete(store):
    cache = store.cache("fr")
    cache.set("k", {"v": 1})
    cache.set("k", {"v": 2})  # refresh overwrites
    assert cache.get("k") == {"v": 2}
    cache.delete("k")
    assert cache.get("k") is None and "k" not in cache
    cache.delete("k")  # deleting a missing key is not an error


def test_report_round_trip_is_byte_exact(store):
    assert store.load_report("MLTM", 2025) is None
    assert store.cached_filing_id("MLTM", 2025) is None
    store.save_report("MLTM", 2025, _meta(), HEBREW_CRLF)
    text, meta = store.load_report("MLTM", 2025)
    assert text == HEBREW_CRLF and text.encode("utf-8") == HEBREW_CRLF.encode("utf-8")
    assert meta == _meta()
    assert store.cached_filing_id("MLTM", 2025) == 32935334
    assert store.load_report("MLTM", 2024) is None
    assert "MLTM" in store.report_location("MLTM", 2025) and "2025" in store.report_location("MLTM", 2025)


def test_report_overwrite_replaces_filing(store):
    store.save_report("MLTM", 2025, _meta(1, "old"), "old")
    store.save_report("MLTM", 2025, _meta(2, "new"), "new")
    text, meta = store.load_report("MLTM", 2025)
    assert (text, meta.filing_id) == ("new", 2)
    assert store.cached_filing_id("MLTM", 2025) == 2


def test_financials_snapshot_saves_and_overwrites(store):
    store.save_financials("MLTM", False, {"company_id": 6901, "periods": []})
    store.save_financials("MLTM", True, {"company_id": 6901, "periods": [{"fy": 2025}]})
    store.save_financials("MLTM", False, {"company_id": 6901, "periods": [{"fy": 2024}]})


FR_RECORDS = [
    {"ts": "t1", "endpoint": "/filings/", "cache": "miss", "credits": 1, "status": 200},
    {"ts": "t2", "endpoint": "/filings/", "cache": "hit", "credits": 0, "status": 200},
    {"ts": "t3", "endpoint": "/filings/7/markdown/", "cache": "refresh", "credits": 6, "status": 200},
    {"ts": "t4", "endpoint": "/usage/", "cache": "miss", "credits": None, "status": None, "error": "X"},
]
LLM_RECORDS = [
    {"ts": "t1", "model": "m", "cost": 0.0123456789, "cache_hit": False, "ok": True},
    {"ts": "t2", "model": "m", "cost": 0.0, "cache_hit": True, "ok": True},
    {"ts": "t3", "model": "m", "cost": None, "cache_hit": False, "ok": False, "error": "bad"},
    {"ts": "t4", "model": "m", "cost": 0.5, "cache_hit": False},  # no "ok" field: counts as ok
]


def test_usage_totals_match_shared_semantics(store):
    assert store.totals("fr") == fr_totals([])
    assert store.totals("llm") == llm_totals([])
    for rec in FR_RECORDS:
        store.log("fr", rec)
    for rec in LLM_RECORDS:
        store.log("llm", rec)
    assert (
        store.totals("fr")
        == fr_totals(FR_RECORDS)
        == {
            "calls": 4,
            "cache_hits": 1,
            "network_calls": 3,
            "credits_logged": 7,
        }
    )
    assert (
        store.totals("llm")
        == llm_totals(LLM_RECORDS)
        == {
            "calls": 4,
            "cache_hits": 1,
            "failures": 1,
            "total_cost_usd": 0.512346,
        }
    )


def test_fr_client_cache_hit_then_cached_mode(store, settings):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/usage/").mock(return_value=httpx.Response(200, json={"credits_used": 5}))
        with FRClient(settings, store=store) as live:
            assert live.request("/usage/", {"x": 1}).json_body() == {"credits_used": 5}
            assert live.request("/usage/", {"x": 1}).json_body() == {"credits_used": 5}
        assert route.call_count == 1  # second call served from the store
    with FRClient(settings, mode="cached", store=store) as cached:
        assert cached.request("/usage/", {"x": 1}).json_body() == {"credits_used": 5}
        assert cached.is_cached("/usage/", {"x": 1})
        with pytest.raises(NotCached):
            cached.request("/usage/", {"x": 2})
    assert store.totals("fr")["cache_hits"] == 2
    assert store.totals("fr")["network_calls"] == 1


def test_ping(store):
    assert store.ping() is True
