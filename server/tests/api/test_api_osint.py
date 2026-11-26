"""OSINT endpoints (add-osint-web): stored result, live streamed run, refusals. Offline (LLM_FAKE)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from stock_analyzer.api.main import create_app
from stock_analyzer.companies import TrackedCompany
from stock_analyzer.errors import NoFindings
from stock_analyzer.osint.models import AREAS
from stock_analyzer.services import osint
from stock_analyzer.services.context import Ctx
from stock_analyzer.store import get_store
from tests.api.test_api import sse_events

TODAY = date(2026, 11, 26)


def track_elal(settings) -> None:
    get_store(settings).add_tracked(
        TrackedCompany(
            ticker="ELAL", name_he="אל על", name_en="El Al Israel Airlines", fr_company_id=1, source="added"
        )
    )


@pytest.fixture
def fake_settings(settings):
    """LLM_FAKE: the research runs offline (fake search and agent models)."""
    s = settings.model_copy(update={"llm_fake": True})
    track_elal(s)
    return s


@pytest.fixture
def client(fake_settings):
    with TestClient(create_app(fake_settings)) as c:
        yield c


def store_result(settings, months: int = 36):
    """A stored result, produced by an offline run through the service."""
    return osint.run_research(Ctx(settings, mode="live"), "ELAL", months, today=TODAY)


class NoProviderCalls:
    """Fails the test if the search backend or agent models are built."""

    def __init__(self, monkeypatch):
        def boom(*_a, **_k):
            raise AssertionError("provider called")

        monkeypatch.setattr(osint, "FakeSearch", boom)
        monkeypatch.setattr(osint, "OpenRouterSearch", boom)
        monkeypatch.setattr(osint, "fake_model_factory", boom)
        monkeypatch.setattr(osint, "live_model_factory", boom)


# ---------------------------------------------------------------- GET: stored result


def test_get_returns_stored_result(client, fake_settings, monkeypatch):
    stored = store_result(fake_settings)
    NoProviderCalls(monkeypatch)
    for mode in ("cached", "live"):  # live mode never spends on GET
        r = client.get("/api/companies/elal/osint", params={"mode": mode})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ticker"] == "ELAL" and body["from_cache"] is True
        assert body["window_months"] == 36 and body["run_date"] == "2026-11-26"
        assert [a["area"] for a in body["scorecard"]["areas"]] == list(AREAS)
        assert [f["id"] for f in body["findings"]] == [f.id for f in stored.findings]
        assert {"published_at", "derived_from_filing", "source_url"} <= set(body["findings"][0])


def test_get_nothing_stored(client, monkeypatch):
    NoProviderCalls(monkeypatch)
    r = client.get("/api/companies/ELAL/osint")
    assert r.status_code == 409 and r.json()["code"] == "not_cached"
    other = client.get("/api/companies/ELAL/osint", params={"months": 12})
    assert other.json()["code"] == "not_cached"


def test_get_other_window_is_separate(client, fake_settings):
    store_result(fake_settings, 12)
    assert client.get("/api/companies/ELAL/osint", params={"months": 12}).status_code == 200
    assert client.get("/api/companies/ELAL/osint").status_code == 409


def test_get_untracked_and_invalid_window(client):
    r = client.get("/api/companies/NOPE/osint")
    assert r.status_code == 404 and r.json()["code"] == "company_not_found"
    for months in (0, 121):
        r = client.get("/api/companies/ELAL/osint", params={"months": months})
        assert r.status_code == 422 and r.json()["code"] == "validation_error"


# ---------------------------------------------------------------- POST: live run


def test_live_run_streams_progress_then_result_and_stores_it(client):
    r = client.post("/api/companies/elal/osint", params={"mode": "live"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    names = [e for e, _ in events]
    assert names[-1] == "done" and names.count("done") == 1 and "error" not in names
    progress = [p for e, p in events if e == "progress"]
    assert progress[0]["step"] == "orchestrator" and progress[-1]["step"] == "synthesis"
    assert all(p["searches_used"] <= p["search_limit"] for p in progress)
    done = events[-1][1]
    assert done["ticker"] == "ELAL" and done["from_cache"] is False and done["findings"]

    stored = client.get("/api/companies/ELAL/osint").json()
    assert stored["from_cache"] is True and stored["findings"] == done["findings"]


def test_live_run_with_window(client):
    r = client.post("/api/companies/ELAL/osint", params={"mode": "live"}, json={"months": 12})
    done = sse_events(r.text)[-1]
    assert done[0] == "done" and done[1]["window_months"] == 12
    assert client.get("/api/companies/ELAL/osint", params={"months": 12}).status_code == 200


def test_cached_mode_refused_before_stream(client, monkeypatch):
    NoProviderCalls(monkeypatch)
    r = client.post("/api/companies/ELAL/osint", params={"mode": "cached"})
    assert r.status_code == 403 and r.json()["code"] == "live_required"


def test_cached_only_server_refused(fake_settings, monkeypatch):
    NoProviderCalls(monkeypatch)
    s = fake_settings.model_copy(update={"allow_live": False})
    with TestClient(create_app(s)) as c:
        r = c.post("/api/companies/ELAL/osint", params={"mode": "live"})
    assert r.status_code == 403 and r.json()["code"] == "live_disabled"


def test_untracked_and_invalid_window_refused(client, monkeypatch):
    NoProviderCalls(monkeypatch)
    r = client.post("/api/companies/NOPE/osint", params={"mode": "live"})
    assert r.status_code == 404 and r.json()["code"] == "company_not_found"
    for months in (0, 121):
        r = client.post("/api/companies/ELAL/osint", params={"mode": "live"}, json={"months": months})
        assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_missing_openrouter_key(settings, monkeypatch):
    NoProviderCalls(monkeypatch)
    s = settings.model_copy(update={"openrouter_api_key": None})
    track_elal(s)
    with TestClient(create_app(s)) as c:
        r = c.post("/api/companies/ELAL/osint", params={"mode": "live"})
    assert r.status_code == 503 and r.json()["code"] == "missing_credential"


def test_run_in_progress_refused(client, monkeypatch):
    osint.acquire_run("ELAL", 36)
    try:
        NoProviderCalls(monkeypatch)
        r = client.post("/api/companies/ELAL/osint", params={"mode": "live"})
        assert r.status_code == 409 and r.json()["code"] == "research_in_progress"
    finally:
        osint.release_run("ELAL", 36)


def test_no_findings_is_an_error_event_and_keeps_old_result(client, fake_settings, monkeypatch):
    old = store_result(fake_settings)

    def no_findings(*_a, **_k):
        raise NoFindings("no usable findings for ELAL")

    monkeypatch.setattr(osint, "run_research", no_findings)
    events = sse_events(client.post("/api/companies/ELAL/osint", params={"mode": "live"}).text)
    assert events == [("error", {"code": "osint_no_findings", "message": "no usable findings for ELAL"})]
    kept = client.get("/api/companies/ELAL/osint").json()
    assert [f["id"] for f in kept["findings"]] == [f.id for f in old.findings]
    # the slot is released after a failed run
    osint.acquire_run("ELAL", 36)
    osint.release_run("ELAL", 36)
