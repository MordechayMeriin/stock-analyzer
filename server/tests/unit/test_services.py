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
    assert (
        f2025[32935334].selected and f2025[32935334].cached and f2025[32935334].document_url.endswith(".pdf")
    )
    assert not f2025[32935333].selected and not f2025[32935333].cached


def test_structure_and_citations(ctx):
    s = reports.report_structure(ctx, "MLTM", 2025)
    assert s.filing_id == 32935334 and s.page_style == "B" and s.page_count == 36
    assert s.document_url.endswith(".pdf")
    risk = next(n for n in s.nodes if n.node_id == "business-22")
    assert risk.number == "22" and risk.printed_pages[0] is not None
    node = reports.node_paragraphs(ctx, "MLTM", 2025, "business-22")
    first = node.paragraphs[0]
    assert first.text == "22 דיון בגורמי סיכון" or "דיון בגורמי סיכון" in first.text
    for p in node.paragraphs:
        assert p.citation_url == f"{s.document_url}#page={p.page_index}" and p.pid.startswith("MLTM-2025-p")
    with pytest.raises(NodeNotFound):
        reports.node_paragraphs(ctx, "MLTM", 2025, "business-99")


def test_page_paragraphs(ctx):
    page = reports.page_paragraphs(ctx, "MLTM", 2025, 12)
    assert page.citation_url.endswith("#page=12") and page.paragraphs
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
