"""Company report endpoints: scores computed from cached data only."""

import pytest
from fastapi.testclient import TestClient

from stock_analyzer.api.main import create_app
from tests.conftest import seed_malam


@pytest.fixture
def client(settings):
    seed_malam(settings)
    with TestClient(create_app(settings)) as c:
        yield c


def test_report_and_axis_detail(client):
    r = client.get("/api/companies/MLTM/report")
    assert r.status_code == 200
    body = r.json()
    assert (
        body["schema_version"] == "1.0" and body["mode"] == "cached" and body["years"] == [2023, 2024, 2025]
    )
    axes = body["profile"]["axes"]
    assert [a["id"] for a in axes][:2] == ["stability", "safety"]
    assert set(axes[0]["scores"][0]) >= {"fiscal_year", "value", "sector_median", "trend", "driver"}

    d = client.get(axes[0]["detail_url"], params={"year": 2024})
    assert d.status_code == 200
    detail = d.json()
    assert detail["axis_id"] == "stability" and detail["fiscal_year"] == 2024
    assert detail["sector_comparison"] is None and detail["factors"]


def test_report_errors(client):
    assert client.get("/api/companies/NOPE/report").json()["code"] == "company_not_found"
    r = client.get("/api/companies/MLTM/report/axes/valuation")
    assert r.status_code == 404 and r.json()["code"] == "axis_not_found"
    r = client.get("/api/companies/MLTM/report/axes/safety", params={"year": 2019})
    assert r.status_code == 404 and r.json()["code"] == "year_not_found"
