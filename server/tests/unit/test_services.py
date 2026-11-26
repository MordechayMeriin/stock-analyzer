import json

import pytest

from stock_analyzer.errors import CompanyNotFound, LiveModeDisabled, NodeNotFound, NotCached, PageNotFound
from stock_analyzer.llm import CallLog
from stock_analyzer.services import companies, filings, reports, usage
from stock_analyzer.services.context import Ctx
from tests.conftest import seed_fr_cache, seed_malam


@pytest.fixture
def ctx(settings):
    seed_malam(settings)
    return Ctx(settings)


def test_companies(ctx):
    (mltm,) = companies.list_tracked(ctx)
    assert (mltm.ticker, mltm.name_he, mltm.fr_company_id) == ("MLTM", "מלם תים", 6901)
    assert companies.get_company(ctx, "mltm").isin == "IL0001560189"
    with pytest.raises(CompanyNotFound):
        companies.get_company(ctx, "NOPE")


def test_search_marks_tracked(ctx, settings):
    seed_fr_cache(
        settings,
        "/companies/",
        {"search": "מלם", "countries": "IL", "view": "full", "page_size": 25},
        {
            "results": [
                {"id": 6901, "name": "Malam-Team Ltd.", "ticker": "MLTM", "isins": ["IL0001560189"]},
                {"id": 5, "name": "Other"},
            ]
        },
    )
    hits = companies.search(ctx, "מלם")
    assert [(h.fr_company_id, h.tracked_ticker) for h in hits] == [(6901, "MLTM"), (5, None)]
    with pytest.raises(NotCached):
        companies.search(ctx, "something else")


def test_filings_selected_and_cached(ctx):
    out = filings.list_filings(ctx, "MLTM")
    years = {y.fiscal_year: y for y in out.years}
    assert list(years) == [2025, 2024, 2023]
    assert years[2025].selected_filing_id == 32935334 and years[2025].report_cached is True
    assert years[2024].selected_filing_id == 63741657 and years[2024].report_cached is False
    f2025 = {f.filing_id: f for f in years[2025].filings}
    assert f2025[32935334].selected and f2025[32935334].cached
    assert (
        "document_url" not in f2025[32935334].model_dump()
        and "viewer_url" not in f2025[32935334].model_dump()
    )
    assert not f2025[32935333].selected and not f2025[32935333].cached


def test_structure_and_paragraphs_without_pdf_links(ctx):
    s = reports.report_structure(ctx, "MLTM", 2025)
    assert s.filing_id == 32935334 and s.page_style == "B" and s.page_count == 36
    assert "document_url" not in s.model_dump()
    risk = next(n for n in s.nodes if n.node_id == "business-22")
    assert risk.number == "22" and risk.printed_pages[0] is not None
    node = reports.node_paragraphs(ctx, "MLTM", 2025, "business-22")
    first = node.paragraphs[0]
    assert first.text == "22 דיון בגורמי סיכון" or "דיון בגורמי סיכון" in first.text
    for p in node.paragraphs:
        assert "citation_url" not in p.model_dump() and p.pid.startswith("MLTM-2025-p")
    with pytest.raises(NodeNotFound):
        reports.node_paragraphs(ctx, "MLTM", 2025, "business-99")


def test_page_paragraphs(ctx):
    page = reports.page_paragraphs(ctx, "MLTM", 2025, 12)
    assert "citation_url" not in page.model_dump() and page.paragraphs
    assert all(p.page_index == 12 for p in page.paragraphs) and page.node_ids
    with pytest.raises(PageNotFound):
        reports.page_paragraphs(ctx, "MLTM", 2025, 999)


def test_report_not_cached(ctx):
    with pytest.raises(NotCached, match="FY2024"):
        reports.report_structure(ctx, "MLTM", 2024)


def test_select_paragraphs(ctx):
    by_node = reports.select_paragraphs(ctx, "MLTM", 2025, node_id="business-19")
    by_pages = reports.select_paragraphs(ctx, "MLTM", 2025, pages=(7, 8))
    assert by_node and {p.page_index for p in by_pages} <= {7, 8}
    with pytest.raises(PageNotFound):
        reports.select_paragraphs(ctx, "MLTM", 2025, pages=(9, 5))


def test_usage_includes_llm_spend(ctx, settings):
    seed_fr_cache(settings, "/usage/", {}, {"free_credits": {"limit": 500, "used": 276, "remaining": 224}})
    log = CallLog(settings.logs_dir / "llm.jsonl")
    log.write(model="m", purpose="playground", cost=0.0125, cache_hit=False, ok=True)
    log.write(model="m", purpose="playground", cost=0.0, cache_hit=True, ok=True)
    out = usage.usage(ctx)
    assert out.provider["free_credits"]["remaining"] == 224 and out.provider_error is None
    assert out.llm["total_cost_usd"] == 0.0125 and out.llm["calls"] == 2
    assert out.fr_log["calls"] >= 1


def test_usage_survives_missing_provider_data(settings):
    out = usage.usage(Ctx(settings))
    assert out.provider is None and "not cached" in out.provider_error


def test_live_mode_refused_when_disabled(settings):
    with pytest.raises(LiveModeDisabled, match="ALLOW_LIVE"):
        Ctx(settings.model_copy(update={"allow_live": False}), mode="live")


def test_parse_is_memoized(ctx, monkeypatch):
    reports.report_structure(ctx, "MLTM", 2025)
    calls = []
    monkeypatch.setattr(reports, "parse_report", lambda *a, **k: calls.append(1))
    reports.report_structure(ctx, "MLTM", 2025)
    assert calls == []
    assert json.loads(reports.report_structure(ctx, "MLTM", 2025).model_dump_json())["ticker"] == "MLTM"


# ---------------------------------------------------------------- unprocessed reports (processing status)

import httpx  # noqa: E402
import respx  # noqa: E402

from stock_analyzer.companies import TrackedCompany  # noqa: E402
from stock_analyzer.ingest.fr_client import FRClient, FRResponse  # noqa: E402

FR_BASE = "https://api.financialreports.eu"
RMLI = TrackedCompany(ticker="RMLI", name_he="רמי לוי", fr_company_id=7010, source="added")


def _rmli_rows(fixtures_dir, **status_by_id):
    rows = json.loads((fixtures_dir / "rmli_dlekg_filings.json").read_text())["results"]
    rows = [r for r in rows if r["company_id"] == 7010]
    return [{**r, "processing_status": status_by_id.get(str(r["id"]), r["processing_status"])} for r in rows]


def _listing(rows):
    return {"count": len(rows), "next": None, "previous": None, "results": rows}


def _seed_rmli_list(settings, rows, *, age):
    """Cache Rami Levy's filing list as if fetched ``age`` ago, and track RMLI."""
    from datetime import UTC, datetime

    params = FRClient._filings_params(7010, "10-K", 1)
    client = FRClient(settings)
    client.cache.set(
        FRClient.cache_key("/filings/", params),
        FRResponse(
            status=200,
            body=json.dumps(_listing(rows), ensure_ascii=False),
            fetched_at=(datetime.now(UTC) - age).isoformat(),
        ).model_dump(),
    )
    client.store.add_tracked(RMLI)
    client.close()


@pytest.fixture
def live_settings(settings):
    return settings.model_copy(update={"allow_live": True})


@respx.mock(base_url=FR_BASE)
def test_refresh_when_provider_finished_since_list_was_cached(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(days=3))
    route = respx_mock.get("/filings/").mock(
        return_value=httpx.Response(200, json=_listing(_rmli_rows(fixtures_dir, **{"61337033": "COMPLETED"})))
    )
    ctx = Ctx(live_settings, mode="live")
    fresh = filings.filings_for(ctx, RMLI, [2024])
    assert route.call_count == 1
    assert next(f for f in fresh if f.id == 61337033).processing_status == "COMPLETED"
    filings.filings_for(ctx, RMLI, [2024])  # the list is fresh now: no second refresh
    assert route.call_count == 1


@respx.mock(base_url=FR_BASE)
def test_live_listing_refreshes_a_stale_list_once(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(days=2))
    route = respx_mock.get("/filings/").mock(
        return_value=httpx.Response(200, json=_listing(_rmli_rows(fixtures_dir, **{"61337033": "COMPLETED"})))
    )
    out = filings.list_filings(Ctx(live_settings, mode="live"), "RMLI")
    assert route.call_count == 1
    fy2024 = next(y for y in out.years if y.fiscal_year == 2024)
    assert [f.filing_id for f in fy2024.filings if f.selected] == [61337033]


@respx.mock(base_url=FR_BASE, assert_all_called=False)
def test_recently_cached_list_is_not_refreshed(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(hours=3))
    route = respx_mock.get("/filings/").mock(return_value=httpx.Response(500))
    out = filings.filings_for(Ctx(live_settings, mode="live"), RMLI, [2024])
    assert route.call_count == 0
    assert next(f for f in out if f.id == 61337033).processing_status == "QUEUED"


@respx.mock(base_url=FR_BASE, assert_all_called=False)
def test_cached_mode_never_refreshes(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(days=30))
    route = respx_mock.get("/filings/").mock(return_value=httpx.Response(500))
    filings.filings_for(Ctx(live_settings), RMLI, [2024])
    filings.list_filings(Ctx(live_settings), "RMLI")
    assert route.call_count == 0


@respx.mock(base_url=FR_BASE, assert_all_called=False)
def test_available_years_never_trigger_a_refresh(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(days=30))
    route = respx_mock.get("/filings/").mock(return_value=httpx.Response(500))
    filings.filings_for(Ctx(live_settings, mode="live"), RMLI, [2025])  # FY2025 is COMPLETED
    assert route.call_count == 0


@respx.mock(base_url=FR_BASE)
def test_live_fetch_of_two_years_refreshes_the_list_once(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(days=3))
    route = respx_mock.get("/filings/").mock(
        return_value=httpx.Response(200, json=_listing(_rmli_rows(fixtures_dir, **{"61337033": "COMPLETED"})))
    )
    text = "# דוח תקופתי\n"
    for filing_id in (61337033, 33051170):
        respx_mock.get(f"/filings/{filing_id}/markdown/").mock(
            return_value=httpx.Response(200, text=text, headers={"X-Total-Chars": str(len(text))})
        )
    out = filings.fetch(Ctx(live_settings, mode="live"), "RMLI", [2024, 2025], financials=False)
    assert route.call_count == 1
    assert [(r.fiscal_year, r.filing_id) for r in out.reports] == [(2024, 61337033), (2025, 33051170)]


def _fr_log(settings):
    p = settings.logs_dir / "fr.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


@respx.mock(base_url=FR_BASE, assert_all_called=False)
def test_unprocessed_report_is_refused_without_a_markdown_call(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    from stock_analyzer.errors import ReportNotProcessed

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(hours=1))
    md = respx_mock.get("/filings/61337033/markdown/").mock(return_value=httpx.Response(404))
    ctx = Ctx(live_settings, mode="live")
    with pytest.raises(ReportNotProcessed, match=r"RMLI FY2024.*61337033.*QUEUED") as exc:
        filings.fetch(ctx, "RMLI", [2024], financials=False)
    assert exc.value.code == "report_not_processed"
    with pytest.raises(ReportNotProcessed):
        reports.report_structure(ctx, "RMLI", 2024)
    assert md.call_count == 0
    assert not any("markdown" in r["endpoint"] for r in _fr_log(live_settings))
    assert ctx.store.cached_filing_id("RMLI", 2024) is None  # nothing saved


@respx.mock(base_url=FR_BASE)
def test_unknown_status_that_404s_is_not_processed(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    from stock_analyzer.errors import ReportNotProcessed

    rows = [{**r, "processing_status": None} for r in _rmli_rows(fixtures_dir)]
    _seed_rmli_list(live_settings, rows, age=timedelta(days=5))
    respx_mock.get("/filings/61337033/markdown/").mock(return_value=httpx.Response(404, json={"detail": "x"}))
    ctx = Ctx(live_settings, mode="live")
    with pytest.raises(ReportNotProcessed, match=r"61337033 \(provider status no status\)"):
        filings.fetch(ctx, "RMLI", [2024], financials=False)
    assert ctx.store.cached_filing_id("RMLI", 2024) is None


@respx.mock(base_url=FR_BASE)
def test_missing_markdown_for_a_completed_filing_stays_not_found(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    from stock_analyzer.errors import ProviderNotFound

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(hours=1))
    respx_mock.get("/filings/33051170/markdown/").mock(return_value=httpx.Response(404, json={"detail": "x"}))
    with pytest.raises(ProviderNotFound) as exc:
        filings.fetch(Ctx(live_settings, mode="live"), "RMLI", [2025], financials=False)
    assert exc.value.code == "upstream_not_found"


@respx.mock(base_url=FR_BASE, assert_all_called=False)
def test_failed_conversion_message(respx_mock, live_settings, fixtures_dir):
    from datetime import timedelta

    from stock_analyzer.errors import ReportNotProcessed

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir, **{"61337033": "FAILED"}), age=timedelta(hours=1))
    with pytest.raises(ReportNotProcessed, match="could not convert"):
        filings.fetch(Ctx(live_settings, mode="live"), "RMLI", [2024], financials=False)


def test_filings_report_markdown_availability(live_settings, fixtures_dir):
    from datetime import timedelta

    _seed_rmli_list(live_settings, _rmli_rows(fixtures_dir), age=timedelta(days=9))
    years = {y.fiscal_year: y for y in filings.list_filings(Ctx(live_settings), "RMLI").years}
    assert (years[2024].selected_filing_id, years[2024].markdown_availability) == (61337033, "processing")
    assert (years[2025].selected_filing_id, years[2025].markdown_availability) == (33051170, "available")
    by_id = {f.filing_id: f for f in years[2024].filings}
    assert by_id[61337033].processing_status == "QUEUED"
    assert by_id[61337001].processing_status == "COMPLETED"  # the HTM cover form


def test_year_without_selection_has_no_availability(live_settings, fixtures_dir):
    from datetime import timedelta

    trustee = {
        "id": 99,
        "company_id": 7010,
        "title": 'דו"ח שנתי – נאמנות למחזיקי אגרות החוב',
        "fiscal_year": 2026,
        "file_extension": "PDF",
        "file_size": 1000,
        "processing_status": "COMPLETED",
    }
    _seed_rmli_list(live_settings, [trustee, *_rmli_rows(fixtures_dir)], age=timedelta(days=1))
    years = {y.fiscal_year: y for y in filings.list_filings(Ctx(live_settings), "RMLI").years}
    assert years[2026].selection_error and years[2026].selected_filing_id is None
    assert years[2026].markdown_availability is None
