"""OSINT endpoints: stored scorecard, live-only runs, errors (analyzer-api spec: OSINT endpoints)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stock_analyzer.api.main import create_app
from stock_analyzer.osint.agents import NoFindings
from stock_analyzer.services import osint


@pytest.fixture
def fake_settings(settings):
    """Fake LLM and fake search: a research run is offline and free."""
    return settings.model_copy(update={"llm_fake": True, "allow_live": True})


@pytest.fixture
def client(fake_settings):
    with TestClient(create_app(fake_settings)) as c:
        yield c


def test_get_before_any_run_is_not_cached(client):
    r = client.get("/api/companies/MLTM/osint")
    assert r.status_code == 409 and r.json()["code"] == "not_cached"
    assert "MLTM" in r.json()["message"]


def test_get_unknown_ticker_404(client):
    r = client.get("/api/companies/NOPE/osint")
    assert r.status_code == 404 and r.json()["code"] == "company_not_found"


def test_run_refused_in_cached_mode(client):
    r = client.post("/api/companies/MLTM/osint")
    assert r.status_code == 403 and r.json()["code"] == "live_required"


def test_run_refused_on_cached_only_server(fake_settings):
    with TestClient(create_app(fake_settings.model_copy(update={"allow_live": False}))) as c:
        r = c.post("/api/companies/MLTM/osint", params={"mode": "live"})
    assert r.status_code == 403 and r.json()["code"] == "live_disabled"


def test_run_then_read_stored_result(client):
    r = client.post("/api/companies/mltm/osint", params={"mode": "live", "months": 24})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["ticker"] == "MLTM" and run["window_months"] == 24 and run["from_cache"] is False
    card = run["scorecard"]
    assert card["overall_label"] in {"stable", "watch", "fragile"}
    assert [a["area"] for a in card["areas"]] == [
        "news",
        "market",
        "credit",
        "operations",
        "labor_government",
        "competition_macro",
    ]
    assert run["findings"] and all(f["source_url"].startswith("http") for f in run["findings"])

    stored = client.get("/api/companies/MLTM/osint", params={"months": 24}).json()
    assert stored["from_cache"] is True and stored["scorecard"] == card
    # another window has its own result
    assert client.get("/api/companies/MLTM/osint").json()["code"] == "not_cached"


@pytest.mark.parametrize("months", [0, 121])
def test_months_out_of_range_is_422(client, months):
    r = client.get("/api/companies/MLTM/osint", params={"months": months})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_no_findings_is_422(client, monkeypatch):
    def nothing(*_args, **_kw):
        raise NoFindings("no usable findings for MLTM")

    monkeypatch.setattr(osint, "run_research", nothing)
    r = client.post("/api/companies/MLTM/osint", params={"mode": "live"})
    assert r.status_code == 422
    assert r.json() == {"code": "osint_no_findings", "message": "no usable findings for MLTM"}
