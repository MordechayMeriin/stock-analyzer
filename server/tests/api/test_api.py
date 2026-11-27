import json
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from stock_analyzer.api.main import create_app
from stock_analyzer.cli import render_structure
from stock_analyzer.llm import FakeLLM
from stock_analyzer.services import reports
from stock_analyzer.services.context import Ctx
from stock_analyzer.services.models import StructureOut
from tests.conftest import FIXTURES, seed_bank_and_insurer, seed_fr_cache, seed_malam


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
    assert body["storage"] == {"backend": "fs", "ok": True}
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


def test_report_not_processed_error(client, monkeypatch):
    from stock_analyzer.errors import ReportNotProcessed

    def not_processed(*_args, **_kw):
        raise ReportNotProcessed("RMLI FY2024: the provider has not processed filing 61337033 (QUEUED)")

    monkeypatch.setattr(reports, "report_structure", not_processed)
    r = client.get("/api/companies/MLTM/reports/2024/structure")
    assert r.status_code == 409
    assert r.json() == {
        "code": "report_not_processed",
        "message": "RMLI FY2024: the provider has not processed filing 61337033 (QUEUED)",
    }


def test_template_not_supported_error(client, monkeypatch):
    from stock_analyzer.errors import TemplateNotSupported
    from stock_analyzer.services import financials

    def unsupported(*_args, **_kw):
        raise TemplateNotSupported("MLTM: no canonical fields for template 'reit'")

    monkeypatch.setattr(financials, "financials", unsupported)
    r = client.get("/api/companies/MLTM/financials")
    assert r.status_code == 422
    assert r.json() == {
        "code": "template_not_supported",
        "message": "MLTM: no canonical fields for template 'reit'",
    }


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


def test_filings_endpoint_reports_processing_status(client):
    body = client.get("/api/companies/MLTM/filings").json()
    fy2025 = next(y for y in body["years"] if y["fiscal_year"] == 2025)
    assert fy2025["markdown_availability"] == "available"
    assert {f["filing_id"]: f["processing_status"] for f in fy2025["filings"]}[32935334] == "COMPLETED"
    for year in body["years"]:
        if year["selection_error"]:
            assert year["markdown_availability"] is None


def test_structure_node_page_endpoints(client):
    s = client.get("/api/companies/MLTM/reports/2025/structure").json()
    assert s["page_count"] == 36 and any(n["node_id"] == "business-22" for n in s["nodes"])
    node = client.get("/api/companies/MLTM/reports/2025/nodes/business-22").json()
    p = node["paragraphs"][0]
    assert set(p) >= {"pid", "text", "page_index", "page_printed"}
    assert "citation_url" not in p and "document_url" not in s  # no links to the source PDF
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
        "/api/companies/{ticker}/ratios",
        "/api/companies/{ticker}/compare",
        "/api/companies/{ticker}/story",
        "/api/companies/{ticker}/reports/{fiscal_year}/structure",
        "/api/companies/{ticker}/reports/{fiscal_year}/nodes/{node_id}",
        "/api/companies/{ticker}/reports/{fiscal_year}/pages/{page_index}",
        "/api/usage",
        "/api/playground",
    ):
        assert path in paths, path
    assert "post" in paths["/api/companies"] and "delete" in paths["/api/companies/{ticker}"]
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
    assert "citations" not in done  # no links to the source document
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


def test_usage_totals_come_from_the_store(client, settings):
    from stock_analyzer.store import get_store

    seed_fr_cache(settings, "/usage/", {}, {"free_credits": {"remaining": 224}})
    store = get_store(settings)
    store.log("fr", {"cache": "miss", "credits": 6})
    store.log("llm", {"cost": 0.125, "cache_hit": False, "ok": True})
    store.log("llm", {"cost": 0.0, "cache_hit": True, "ok": True})
    store.close()
    body = client.get("/api/usage").json()
    assert body["llm"] == {"calls": 2, "cache_hits": 1, "failures": 0, "total_cost_usd": 0.125}
    # the logged miss, plus the usage request itself served from cache
    assert body["fr_log"] == {"calls": 2, "cache_hits": 1, "network_calls": 1, "credits_logged": 6}


# ---------------------------------------------------------------- report comparison (report-diff)


def test_compare_endpoint_and_cli_parity(settings):
    from stock_analyzer.cli import render_comparison
    from stock_analyzer.diff.align import Comparison
    from stock_analyzer.services import compare
    from tests.conftest import seed_business_slices

    seed_business_slices(settings)
    with TestClient(create_app(settings)) as c:
        response = c.get("/api/companies/MLTM/compare", params={"years": [2023, 2024, 2025]})
        assert response.status_code == 200, response.text
        api = Comparison.model_validate(response.json())
        assert c.get("/api/companies/MLTM/compare", params={"years": [2025]}).status_code == 422
    assert api.years == [2023, 2024, 2025]
    tax = next(s for s in api.sections if s.title == "מיסוי")
    assert [p.status for p in tax.pairs] == ["changed", "unchanged"]
    cli = compare.compare(Ctx(settings), "MLTM", [2023, 2024, 2025])
    assert api == cli
    assert render_comparison(api) == render_comparison(cli)


# ---------------------------------------------------------------- company story (company-story)


@pytest.fixture
def story_settings(settings):
    """Malam with a full FY2025 fixture (directors' report, document URL) and FY2023/FY2024 slices."""
    from stock_analyzer.ingest.fr_client import Filing, save_report
    from tests.conftest import fixture_text, seed_malam

    seed_malam(settings)
    for fy, filing_id in ((2023, 63741686), (2024, 63741657)):
        filing = Filing(id=filing_id, title=f"Periodic and annual report for {fy}", fiscal_year=fy)
        save_report(settings, "MLTM", fy, filing, fixture_text(f"mltm_{fy}_business_slice.md"))
    return settings


def scripted_models(settings, finals):
    from stock_analyzer.agents_model import FakeAgentModels
    from stock_analyzer.story.pipeline import prepare_story
    from tests.unit.test_story_pipeline import AS_OF, storyteller_script

    with closing(Ctx(settings)) as c:
        prep = prepare_story(c, "MLTM", as_of=AS_OF)
    script = storyteller_script(prep, [f(prep) for f in finals])
    return FakeAgentModels(settings=settings, script={"story.storyteller": script})


def good(prep):
    from tests.unit.test_story_pipeline import good_story

    return lambda der: good_story(prep, der)


def bad(prep):
    from tests.unit.test_story_pipeline import good_story

    story = good_story(prep)
    story["what_it_does"][0]["text_he"] = "הכנסות של 4.1 מיליארד."
    return story


def test_story_live_run_then_saved_story(story_settings):
    from stock_analyzer.story.pipeline import StoryRun

    app = create_app(story_settings)
    app.state.agent_models = scripted_models(story_settings, [good])
    with TestClient(app) as c:
        missing = c.get("/api/companies/MLTM/story")
        assert missing.status_code == 409 and missing.json()["code"] == "not_cached"

        response = c.post("/api/companies/MLTM/story", json={"mode": "live", "as_of": "2026-11-26"})
        assert response.status_code == 200
        events = sse_events(response.text)
        names = [n for n, _ in events]
        assert names[0] == "progress" and names[-1] == "done" and "error" not in names
        steps = [d["step"] for n, d in events if n == "progress"]
        assert steps[0] == "reports" and "verify" in steps and "saved" in steps
        done = StoryRun.model_validate(events[-1][1])

        saved = c.get("/api/companies/MLTM/story")
        assert saved.status_code == 200
        body = saved.json()
    assert body["run_id"] == done.run_id
    revenue = next(f for f in body["facts"] if f["fact_id"] == "FIN:revenue:2025")
    assert revenue["value"] == "4138004000" and isinstance(revenue["value"], str)
    assert body["citations"] and all("url" not in c for c in body["citations"].values())  # no PDF links


def test_story_and_compare_resolve_runtime_added_companies(settings):
    """A company added at runtime (not in companies.yaml) is tracked for the story and compare too."""
    from stock_analyzer.companies import TrackedCompany
    from stock_analyzer.store import get_store

    get_store(settings).add_tracked(
        TrackedCompany(ticker="ELAL", fr_company_id=6759, name_he="אל על", source="added")
    )
    with TestClient(create_app(settings)) as c:
        story = c.get("/api/companies/ELAL/story")
        compare = c.get("/api/companies/ELAL/compare", params=[("years", 2024), ("years", 2025)])
    assert story.status_code == 409 and story.json()["code"] == "not_cached"  # no saved story yet
    assert compare.json().get("code") != "company_not_found"


def test_story_run_refused_in_cached_mode(story_settings):
    with TestClient(create_app(story_settings)) as c:
        r = c.post("/api/companies/MLTM/story", json={"mode": "cached"})
    assert r.status_code == 403 and "live mode" in r.json()["message"]


def test_story_run_over_budget_rejected_before_streaming(story_settings):
    small = story_settings.model_copy(update={"story_max_tokens": 1000})
    app = create_app(small)
    app.state.agent_models = scripted_models(story_settings, [good])
    with TestClient(app) as c:
        r = c.post("/api/companies/MLTM/story", json={"mode": "live", "as_of": "2026-11-26"})
    assert (
        r.status_code == 413
        and r.json()["code"] == "story_too_large"
        and "1,000-token" in r.json()["message"]
    )


def test_story_failed_verification_is_an_error_event(story_settings):
    app = create_app(story_settings)
    app.state.agent_models = scripted_models(story_settings, [bad, bad])
    with TestClient(app) as c:
        r = c.post("/api/companies/MLTM/story", json={"mode": "live", "as_of": "2026-11-26"})
        events = sse_events(r.text)
        assert events[-1][0] == "error" and events[-1][1]["code"] == "story_verification_failed"
        assert c.get("/api/companies/MLTM/story").status_code == 409  # nothing saved


def web_cited(prep):
    """A storyteller turn that cites the first result of its search as extra evidence."""
    import json

    from tests.unit.test_story_pipeline import good_story

    def final(turn):
        sid = json.loads(turn.tool_outputs()[-1])["results"][0]["source_id"]
        story = good_story(prep)
        story["story_vs_numbers"][0]["fact_ids"] = ["CHG:revenue:2024-2025"]
        story["story_vs_numbers"][0]["text_he"] = "הנתונים תומכים: {{CHG:revenue:2024-2025}}."
        story["story_vs_numbers"][0]["source_ids"] = [sid]
        return story

    return final


def test_story_saved_with_web_sources(story_settings):
    from stock_analyzer.agents_model import FakeAgentModels, tool_call
    from stock_analyzer.story.pipeline import prepare_story
    from tests.unit.test_story_pipeline import AS_OF

    with closing(Ctx(story_settings)) as c:
        prep = prepare_story(c, "MLTM", as_of=AS_OF)
    app = create_app(story_settings)
    app.state.agent_models = FakeAgentModels(
        settings=story_settings,
        script={"story.storyteller": [tool_call("web_search", query="מלם"), web_cited(prep)]},
    )
    with TestClient(app) as c:
        r = c.post("/api/companies/MLTM/story", json={"mode": "live", "as_of": "2026-11-26"})
        events = sse_events(r.text)
        assert events[-1][0] == "done", events[-1]
        osint_steps = [d["message"] for n, d in events if n == "progress" and d["step"] == "osint"]
        assert any("research started" in m for m in osint_steps)
        body = c.get("/api/companies/MLTM/story").json()
    [sid] = body["story"]["story_vs_numbers"][0]["source_ids"]
    source = body["web_sources"][sid]
    assert source["url"].startswith("https://") and source["title"] and source["published_at"]
    assert source["excerpts"] and body["rendered"]["story_vs_numbers"][0]["source_ids"] == [sid]
    assert body["searches"] == ["מלם"] and body["osint"]["started"] is True


def test_story_run_refused_while_research_runs(story_settings):
    from stock_analyzer.services import osint as osint_service

    app = create_app(story_settings)
    app.state.agent_models = scripted_models(story_settings, [good])
    osint_service.acquire_run("MLTM", story_settings.osint_window_months)
    try:
        with TestClient(app) as c:
            r = c.post("/api/companies/MLTM/story", json={"mode": "live", "as_of": "2026-11-26"})
    finally:
        osint_service.release_run("MLTM", story_settings.osint_window_months)
    assert r.status_code == 409 and r.json()["code"] == "research_in_progress"


def test_story_search_limit_is_an_error_event(story_settings):
    from stock_analyzer.agents_model import FakeAgentModels, tool_call

    one = story_settings.model_copy(update={"story_max_searches": 1})
    app = create_app(one)
    app.state.agent_models = FakeAgentModels(
        settings=one,
        script={
            "story.storyteller": [tool_call("web_search", query="a"), tool_call("web_search", query="b")]
        },
    )
    with TestClient(app) as c:
        r = c.post("/api/companies/MLTM/story", json={"mode": "live", "as_of": "2026-11-26"})
        events = sse_events(r.text)
        assert events[-1][0] == "error" and events[-1][1]["code"] == "story_search_limit"
        assert "'a'" in events[-1][1]["message"]
        assert c.get("/api/companies/MLTM/story").status_code == 409  # nothing saved


# ---------------------------------------------------------------- tracking companies at runtime

ABC = {"fr_company_id": 1234, "ticker": "abc", "name_he": "חברה לדוגמה", "name_en": "Example Ltd."}


@pytest.fixture
def live_client(settings):
    seed_malam(settings)
    with TestClient(create_app(settings.model_copy(update={"allow_live": True}))) as c:
        yield c


def test_companies_list_reports_source(live_client):
    assert [(c["ticker"], c["source"]) for c in live_client.get("/api/companies").json()] == [
        ("MLTM", "registry")
    ]


def test_add_then_remove_company_in_live_mode(live_client):
    r = live_client.post("/api/companies", params={"mode": "live"}, json=ABC)
    assert r.status_code == 201
    assert r.json() == {**ABC, "ticker": "ABC", "isin": None, "source": "added"}
    listed = live_client.get("/api/companies").json()  # cached mode reads it too
    assert [(c["ticker"], c["source"]) for c in listed] == [("MLTM", "registry"), ("ABC", "added")]
    assert live_client.get("/api/companies/abc").json()["fr_company_id"] == 1234

    r = live_client.delete("/api/companies/abc", params={"mode": "live"})
    assert r.status_code == 204 and r.content == b""
    assert [c["ticker"] for c in live_client.get("/api/companies").json()] == ["MLTM"]
    assert live_client.get("/api/companies/ABC").json()["code"] == "company_not_found"


def test_add_and_remove_refused_in_cached_mode(live_client):
    r = live_client.post("/api/companies", json=ABC)
    assert r.status_code == 403 and r.json()["code"] == "live_required"
    r = live_client.delete("/api/companies/MLTM")
    assert r.status_code == 403 and r.json()["code"] == "live_required"
    assert len(live_client.get("/api/companies").json()) == 1


def test_add_refused_on_cached_only_server(settings):
    with TestClient(create_app(settings.model_copy(update={"allow_live": False}))) as c:
        r = c.post("/api/companies", params={"mode": "live"}, json=ABC)
        assert r.status_code == 403 and r.json()["code"] == "live_disabled"
        assert [x["ticker"] for x in c.get("/api/companies").json()] == ["MLTM"]


@pytest.mark.parametrize(
    "change", [{"ticker": "mltm"}, {"fr_company_id": 6901}], ids=["ticker", "provider_id"]
)
def test_add_already_tracked_is_409(live_client, change):
    r = live_client.post("/api/companies", params={"mode": "live"}, json={**ABC, **change})
    assert r.status_code == 409 and r.json()["code"] == "company_already_tracked"
    assert "MLTM" in r.json()["message"]


def test_add_invalid_ticker_is_422(live_client):
    r = live_client.post("/api/companies", params={"mode": "live"}, json={**ABC, "ticker": "A B/C"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_remove_registry_company_is_409_and_unknown_is_404(live_client):
    r = live_client.delete("/api/companies/MLTM", params={"mode": "live"})
    assert r.status_code == 409 and r.json()["code"] == "company_not_removable"
    r = live_client.delete("/api/companies/NOPE", params={"mode": "live"})
    assert r.status_code == 404 and r.json()["code"] == "company_not_found"


def test_cors_preflight_allows_delete(settings):
    app = create_app(settings.model_copy(update={"cors_origins": ("https://ui.example",)}))
    with TestClient(app) as c:
        r = c.options(
            "/api/companies/ABC",
            headers={"Origin": "https://ui.example", "Access-Control-Request-Method": "DELETE"},
        )
    assert r.status_code == 200
    assert "DELETE" in r.headers["access-control-allow-methods"]


# -- ratios endpoint (analyzer-api spec: Ratios endpoint)


def _floats(node) -> list:
    if isinstance(node, float):
        return [node]
    if isinstance(node, dict):
        return [f for v in node.values() for f in _floats(v)]
    if isinstance(node, list):
        return [f for v in node for f in _floats(v)]
    return []


def test_malam_ratios_endpoint(client):
    r = client.get("/api/companies/MLTM/ratios")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template"] == "industrial" and body["years"] == [2025, 2024, 2023, 2022, 2021]
    groups = {g["group"]: g for g in body["groups"]}
    gross = next(x for x in groups["profitability"]["ratios"] if x["code"] == "gross_margin")
    assert gross["values"]["2025"]["value"] == "0.104733"
    quick = next(x for x in groups["liquidity"]["ratios"] if x["code"] == "quick_ratio")
    assert (
        quick["values"]["2021"]["value"] is None
        and "receivables" in quick["values"]["2021"]["missing_reason"]
    )
    assert _floats(body) == []  # every number is a decimal string


def test_ratios_low_confidence_value(client):
    body = client.get("/api/companies/MLTM/ratios").json()
    roe = next(x for g in body["groups"] for x in g["ratios"] if x["code"] == "roe")["values"]["2025"]
    assert roe["confidence"] == "low" and "BS5" in roe["failed_checks"]


def test_ratios_bank_and_insurer(settings, client):
    seed_bank_and_insurer(settings)
    leumi = client.get("/api/companies/LUMI/ratios").json()
    assert leumi["template"] == "bank" and leumi["years"] == [2025, 2024, 2023]
    harel = client.get("/api/companies/HARL/ratios").json()
    codes = {x["code"] for g in harel["groups"] for x in g["ratios"]}
    assert "roe" in codes and "gross_margin" not in codes


def test_ratios_not_cached(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.get("/api/companies/MLTM/ratios")
    assert r.status_code == 409 and r.json()["code"] == "not_cached"


def test_ratios_unsupported_template(settings, client):
    data = json.loads((FIXTURES / "mltm_financials.json").read_text())
    data["template"] = "reit"
    seed_fr_cache(settings, "/companies/6901/financials/", {"fiscal_period": "FY"}, data)
    r = client.get("/api/companies/MLTM/ratios")
    assert r.status_code == 422 and r.json()["code"] == "template_not_supported"
    assert "reit" in r.json()["message"] and "MLTM" in r.json()["message"]
