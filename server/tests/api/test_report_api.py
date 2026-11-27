"""Report endpoints (analyzer-api spec: company report and axis detail)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stock_analyzer.agents_model import FakeAgentModels
from stock_analyzer.api.main import create_app
from stock_analyzer.report.rater import PURPOSE
from stock_analyzer.services import report as report_service
from stock_analyzer.services.context import Ctx
from tests.unit.report_helpers import rater_output, story_run
from tests.unit.test_report_service import ELAL


@pytest.fixture
def client(settings):
    ctx = Ctx(settings=settings)
    ctx.store.add_tracked(ELAL)
    ctx.store.save_story_run("ELAL", story_run().model_dump(mode="json"))
    with TestClient(create_app(settings)) as c:
        yield c


def build(settings):
    fakes = FakeAgentModels(settings=settings, script={PURPOSE: [rater_output()]})
    return report_service.get_report(Ctx(settings=settings, mode="live"), "ELAL", models=fakes)


def test_not_cached_before_build(client):
    r = client.get("/api/companies/ELAL/report", params={"mode": "cached"})
    assert r.status_code == 409 and r.json()["code"] == "not_cached"
    assert "live mode" in r.json()["message"]


def test_cached_report_and_axis_detail(client, settings):
    built = build(settings)
    r = client.get("/api/companies/ELAL/report", params={"mode": "cached"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "cached" and body["years"] == [2023, 2024, 2025]
    assert [a["id"] for a in body["profile"]["axes"]] == [a.id for a in built.profile.axes]
    assert "currency" not in body["key_metrics"][1]  # optional, non-nullable fields are left out

    d = client.get("/api/companies/ELAL/report/axes/growth", params={"year": 2025})
    assert d.status_code == 200
    assert set(d.json()) >= {"axis_id", "fiscal_year", "headline", "factors", "text"}


def test_unknown_axis_is_not_found(client, settings):
    build(settings)
    r = client.get("/api/companies/ELAL/report/axes/valuation", params={"year": 2025})
    assert r.status_code == 404 and r.json()["code"] == "axis_not_found"


def test_openapi_lists_report_endpoints(client):
    doc = client.get("/openapi.json").json()
    assert "/api/companies/{ticker}/report" in doc["paths"]
    assert "/api/companies/{ticker}/report/axes/{axis_id}" in doc["paths"]
    assert {"CompanyReport", "AxisDetail"} <= set(doc["components"]["schemas"])
    json.dumps(doc)
