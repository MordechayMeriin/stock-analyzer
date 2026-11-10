import json

import pytest
from fastapi.testclient import TestClient

from stock_analyzer.api.main import create_app
from stock_analyzer.cli import render_structure
from stock_analyzer.llm import FakeLLM
from stock_analyzer.services import reports
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import StructureOut
from tests.conftest import seed_fr_cache, seed_malam


@pytest.fixture
def client(settings):
    seed_malam(settings)
    with TestClient(create_app(settings)) as c:
        yield c


def sse_events(text: str) -> list[tuple[str, dict]]:
    events, name = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and name:
            events.append((name, json.loads(line.split(":", 1)[1].strip())))
            name = None
    return events


# ---------------------------------------------------------------- 6.2 app, errors, modes, health


def test_health_reports_credential_flags_without_values(settings):
    with TestClient(create_app(settings)) as c:
        body = c.get("/health").json()
    assert body["status"] == "ok" and body["allow_live"] is True
    assert body["credentials"] == {"fr_api_key": True, "openrouter_api_key": True}
    assert "DO-NOT-LOG" not in json.dumps(body)
    bare = settings.model_copy(update={"fr_api_key": None, "openrouter_api_key": None, "allow_live": False})
    with TestClient(create_app(bare)) as c:
        body = c.get("/health").json()
    assert (
        body["credentials"] == {"fr_api_key": False, "openrouter_api_key": False}
        and body["allow_live"] is False
    )


def test_unknown_ticker_404(client):
    r = client.get("/api/companies/NOPE")
    assert r.status_code == 404 and r.json()["code"] == "company_not_found" and "NOPE" in r.json()["message"]


def test_not_cached_error(client):
    r = client.get("/api/companies/MLTM/reports/2024/structure")
    assert r.status_code == 409 and r.json()["code"] == "not_cached"


def test_live_refused_when_disabled(settings):
    seed_malam(settings)
    app = create_app(settings.model_copy(update={"allow_live": False}))
    with TestClient(app) as c:
        r = c.get("/api/companies/MLTM/filings", params={"mode": "live"})
        assert r.status_code == 403 and r.json()["code"] == "live_disabled"
        assert c.get("/api/companies/MLTM/filings").status_code == 200  # cached still works


def test_validation_error_shape(client):
    r = client.get("/api/companies/MLTM/filings", params={"mode": "sometimes"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_cors_allows_only_configured_origins(settings):
    app = create_app(settings.model_copy(update={"cors_origins": ("https://ui.example",)}))
    with TestClient(app) as c:
        ok = c.get("/health", headers={"Origin": "https://ui.example"})
        bad = c.get("/health", headers={"Origin": "https://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "https://ui.example"
    assert "access-control-allow-origin" not in bad.headers


# ---------------------------------------------------------------- 6.3 endpoints


def test_companies_endpoints(client, settings):
    assert client.get("/api/companies").json()[0]["ticker"] == "MLTM"
    assert client.get("/api/companies/mltm").json()["fr_company_id"] == 6901
    seed_fr_cache(
        settings,
        "/companies/",
        {"search": "מלם", "countries": "IL", "view": "full", "page_size": 25},
        {"results": [{"id": 6901, "name": "Malam-Team Ltd.", "ticker": "MLTM"}]},
    )
    hits = client.get("/api/companies/search", params={"q": "מלם"}).json()
    assert hits[0]["tracked_ticker"] == "MLTM"


def test_filings_endpoint_marks_selected(client):
    body = client.get("/api/companies/MLTM/filings").json()
    fy2025 = next(y for y in body["years"] if y["fiscal_year"] == 2025)
    assert fy2025["selected_filing_id"] == 32935334 and fy2025["report_cached"] is True
    assert [f["filing_id"] for f in fy2025["filings"] if f["selected"]] == [32935334]


def test_structure_node_page_endpoints(client):
    s = client.get("/api/companies/MLTM/reports/2025/structure").json()
    assert s["page_count"] == 36 and any(n["node_id"] == "business-22" for n in s["nodes"])
    node = client.get("/api/companies/MLTM/reports/2025/nodes/business-22").json()
    p = node["paragraphs"][0]
    assert set(p) >= {"pid", "text", "page_index", "page_printed", "citation_url"}
    assert p["citation_url"].endswith(f"#page={p['page_index']}")
    page = client.get(f"/api/companies/MLTM/reports/2025/pages/{p['page_index']}").json()
    assert page["page_index"] == p["page_index"] and page["paragraphs"]
    assert client.get("/api/companies/MLTM/reports/2025/nodes/nope").json()["code"] == "node_not_found"
    assert client.get("/api/companies/MLTM/reports/2025/pages/999").status_code == 404


def test_financials_decimals_are_strings(client):
    body = client.get("/api/companies/MLTM/financials").json()
    assert body["currency"] == "ILS" and body["years"][0] == 2025
    raw = json.dumps(body)
    income = next(s for s in body["statements"] if s["statement"] == "income")
    revenue = next(i for i in income["items"] if i["code"] == "revenue")
    assert revenue["values"]["2025"] == "4138004000"
    for st in body["statements"]:
        for it in st["items"]:
            assert all(v is None or isinstance(v, str) for v in it["values"].values())
    assert "4138004000.0" not in raw
    late = client.get("/api/companies/MLTM/financials", params={"as_of": "2024-04-01"}).json()
    assert 2023 not in late["years"]


def test_usage_endpoint(client, settings):
    seed_fr_cache(settings, "/usage/", {}, {"free_credits": {"remaining": 224}})
    body = client.get("/api/usage").json()
    assert body["provider"]["free_credits"]["remaining"] == 224 and "total_cost_usd" in body["llm"]


def test_cli_api_structure_parity(client, settings):
    api = StructureOut.model_validate(client.get("/api/companies/MLTM/reports/2025/structure").json())
    cli = reports.report_structure(Ctx(settings), "MLTM", 2025)
    assert [(n.node_id, n.title, n.pages) for n in api.nodes] == [
        (n.node_id, n.title, n.pages) for n in cli.nodes
    ]
    assert render_structure(api) == render_structure(cli)


def test_openapi_lists_every_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/health",
        "/api/companies",
        "/api/companies/search",
        "/api/companies/{ticker}",
        "/api/companies/{ticker}/filings",
        "/api/companies/{ticker}/financials",
        "/api/companies/{ticker}/reports/{fiscal_year}/structure",
        "/api/companies/{ticker}/reports/{fiscal_year}/nodes/{node_id}",
        "/api/companies/{ticker}/reports/{fiscal_year}/pages/{page_index}",
        "/api/usage",
        "/api/playground",
    ):
        assert path in paths, path
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"PlaygroundDone", "PlaygroundDelta", "ErrorOut", "StructureOut"} <= set(schemas)


# ---------------------------------------------------------------- 6.4 playground (SSE)


def test_playground_streams_deltas_then_done(settings):
    seed_malam(settings)
    app = create_app(settings)
    app.state.llm = FakeLLM(
        settings=settings, script={"playground": "הסיכון העיקרי הוא תלות בתקציבי המדינה."}, chunk_chars=8
    )
    with TestClient(app) as c:
        r = c.post(
            "/api/playground",
            json={
                "ticker": "MLTM",
                "fiscal_year": 2025,
                "node_id": "business-22.1",
                "question": "מה הסיכונים?",
            },
        )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    names = [e for e, _ in events]
    assert names[-1] == "done" and set(names[:-1]) == {"delta"} and len(names) > 2
    assert "".join(d["text"] for e, d in events if e == "delta") == "הסיכון העיקרי הוא תלות בתקציבי המדינה."
    done = events[-1][1]
    assert (
        done["usage"]["cost"] == 0.0
        and done["paragraph_ids"]
        and all(p.startswith("MLTM-2025-p") for p in done["paragraph_ids"])
    )
    assert all(u.endswith(f"#page={int(pid.split('-p')[1][:4])}") for pid, u in done["citations"].items())
    call = app.state.llm.calls[0]
    assert call.role == "main" and "מה הסיכונים?" in call.user and done["paragraph_ids"][0] in call.user
    assert "Answer in Hebrew" in call.system


def test_playground_rejects_oversized_selection(settings):
    seed_malam(settings)
    app = create_app(settings.model_copy(update={"playground_max_tokens": 50}))
    app.state.llm = FakeLLM(settings=settings)
    with TestClient(app) as c:
        r = c.post(
            "/api/playground",
            json={"ticker": "MLTM", "fiscal_year": 2025, "pages": {"first": 1, "last": 36}, "question": "?"},
        )
    assert (
        r.status_code == 413
        and r.json()["code"] == "selection_too_large"
        and "narrower" in r.json()["message"]
    )
    assert app.state.llm.calls == []


def test_playground_needs_live_mode_for_paid_llm(settings):
    seed_malam(settings)
    with TestClient(create_app(settings)) as c:
        r = c.post(
            "/api/playground",
            json={"ticker": "MLTM", "fiscal_year": 2025, "node_id": "business-19", "question": "?"},
        )
    assert r.status_code == 403 and r.json()["code"] == "live_disabled"


def test_playground_fake_llm_server_works_in_cached_mode(settings):
    seed_malam(settings)
    with TestClient(create_app(settings.model_copy(update={"llm_fake": True}))) as c:
        r = c.post(
            "/api/playground",
            json={"ticker": "MLTM", "fiscal_year": 2025, "node_id": "business-19", "question": "?"},
        )
    assert [e for e, _ in sse_events(r.text)][-1] == "done"


def test_playground_selection_validation(client):
    r = client.post("/api/playground", json={"ticker": "MLTM", "fiscal_year": 2025, "question": "?"})
    assert r.status_code == 422 and "exactly one" in r.json()["message"]


def test_playground_llm_failure_is_an_error_event(settings):
    seed_malam(settings)

    class Boom(FakeLLM):
        def stream_text(self, *a, **k):
            yield from ()
            raise RuntimeError("provider down")

    app = create_app(settings)
    app.state.llm = Boom(settings=settings)
    with TestClient(app) as c:
        r = c.post(
            "/api/playground",
            json={"ticker": "MLTM", "fiscal_year": 2025, "node_id": "business-19", "question": "?"},
        )
    ((name, data),) = [e for e in sse_events(r.text)]
    assert name == "error" and data["code"] == "internal_error"
