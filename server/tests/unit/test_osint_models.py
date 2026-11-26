"""OSINT block-list matching and data models (osint-research spec)."""

from __future__ import annotations

import pytest

from stock_analyzer.osint.blocklist import load_blocklist
from stock_analyzer.osint.models import (
    AREAS,
    AreaReport,
    CompanyProfile,
    DuplicateGroups,
    Finding,
    ResearchResult,
    Scorecard,
    VerdictBatch,
    normalize_url,
)

# ---------------------------------------------------------------- block-list


@pytest.fixture
def blocklist(tmp_path):
    path = tmp_path / "bl.yaml"
    path.write_text(
        "global:\n"
        "  - maya.tase.co.il\n"
        "  - '*.example.org'\n"
        "companies:\n"
        "  ELAL:\n"
        "    - ir.elal.com\n"
        "    - finance.yahoo.com/quote/ELAL.TA/financials\n"
        "  OTHER:\n"
        "    - other.example.com\n",
        encoding="utf-8",
    )
    return load_blocklist("elal", path)


@pytest.mark.parametrize(
    "url",
    [
        "https://maya.tase.co.il/reports/details/123",  # domain
        "https://www.maya.tase.co.il/x",  # subdomain of a plain entry
        "https://news.example.org/a",  # wildcard subdomain
        "https://ir.elal.com/media/tv5lg5s5/pr-q1-2026-en.pdf",  # per-ticker domain
        "https://finance.yahoo.com/quote/ELAL.TA/financials/",  # path prefix
        "https://finance.yahoo.com/quote/ELAL.TA/financials/quarterly",  # below the path prefix
        "HTTPS://MAYA.TASE.CO.IL/",  # case-insensitive
        "not a url",  # unparseable: blocked
    ],
)
def test_blocked_urls(blocklist, url):
    assert blocklist.blocks(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://market.tase.co.il/en/market_data/security/1082379",  # TASE market data is allowed
        "https://example.org/a",  # *.example.org does not cover the bare domain
        "https://finance.yahoo.com/quote/ELAL.TA/",  # quote page, not the financials path
        "https://finance.yahoo.com/quote/ELAL.TA/financialsX",  # prefix must end at a path segment
        "https://www.globes.co.il/news/article.aspx?did=1",
        "https://other.example.com/",  # another ticker's entry
        "https://notir.elal.com.evil.net/",  # suffix tricks
    ],
)
def test_allowed_urls(blocklist, url):
    assert not blocklist.blocks(url)


def test_exclude_domains_has_global_and_ticker_entries(blocklist):
    assert blocklist.exclude_domains == [
        "maya.tase.co.il",
        "*.example.org",
        "ir.elal.com",
        "finance.yahoo.com/quote/ELAL.TA/financials",
    ]


def test_repository_blocklist_covers_filing_sites():
    bl = load_blocklist("ELAL")
    for url in (
        "https://maya.tase.co.il/he/reports/1",
        "https://mayafiles.tase.co.il/rpdf/1.pdf",
        "https://www.magna.isa.gov.il/details.aspx",
        "https://api.financialreports.eu/filings/1",
    ):
        assert bl.blocks(url), url
    # only the filings are excluded: IR site, market data and news stay open
    for url in (
        "https://www.calcalist.co.il/market/article/abc",
        "https://ir.elal.com/eng/home",
        "https://finance.yahoo.com/quote/ELAL.TA/",
        "https://market.tase.co.il/en/market_data/security/1082379",
    ):
        assert not bl.blocks(url), url


# ---------------------------------------------------------------- models


def test_agent_output_models_validate_sample_json():
    report = AreaReport.model_validate_json(
        '{"findings": [{"claim": "S&P Maalot affirmed ilA", "signal": "positive", "confidence": "high",'
        ' "source_url": "https://www.globes.co.il/a", "source_title": "Globes", "published_at": "2026-09-01",'
        ' "derived_from_filing": false}], "summary": "Rating stable."}'
    )
    assert isinstance(report.findings[0], Finding)
    card = Scorecard.model_validate(
        {
            "overall_label": "watch",
            "overall_rationale": "x",
            "overall_trend": "stable",
            "overall_trend_reason": "x",
            "key_drivers": [{"driver": "demand", "status": "positive", "explanation": "x", "finding_ids": ["F1"]}],
            "areas": [
                {
                    "area": a,
                    "label": "stable",
                    "importance": "high",
                    "assessment": "x",
                    "trend": "stable",
                    "trend_reason": "x",
                    "finding_ids": [],
                }
                for a in AREAS
            ],
            "risks": [{"text": "x", "finding_ids": ["F1"]}],
            "strengths": [],
            "summary_he": "סיכום",
        }
    )
    assert len(card.areas) == 6


def test_agent_output_models_have_no_defaults():
    # strict JSON schemas sent by the SDK must mark every field required
    for model in (Finding, AreaReport, Scorecard, CompanyProfile, VerdictBatch, DuplicateGroups):
        schema = model.model_json_schema()
        assert set(schema["required"]) == set(schema["properties"]), model.__name__


def test_normalize_url():
    assert normalize_url("HTTPS://Example.COM/Path/#frag") == "https://example.com/Path"
    assert normalize_url("https://example.com/") == normalize_url("https://example.com")


def test_result_stored_before_the_change_still_loads():
    """Shape of the first live ELAL result: no trends, importance, drivers, verdicts, profile or merged."""
    old = {
        "ticker": "ELAL",
        "company_name": "El Al Israel Airlines Ltd.",
        "run_date": "2026-11-26",
        "window_months": 36,
        "window_start": "2023-11-26",
        "model": "openai/gpt-6.1-sol",
        "scorecard": {
            "overall_label": "watch",
            "overall_rationale": "r",
            "areas": [{"area": a, "label": "watch", "assessment": "a", "finding_ids": ["F1"]} for a in AREAS],
            "risks": [{"text": "r", "finding_ids": ["F1"]}],
            "strengths": [],
            "summary_he": "s",
        },
        "findings": [
            {
                "id": "F1",
                "area": "news",
                "claim": "c",
                "signal": "negative",
                "confidence": "high",
                "source_url": "https://www.globes.co.il/a",
                "source_title": "t",
                "published_at": "2026-11-01",
                "derived_from_filing": False,
            }
        ],
        "dropped": {"blocked": 0, "not_searched": 0, "outside_window": 0},
        "searches_used": 40,
        "search_limit": 40,
        "cost_usd": 0.96,
    }
    r = ResearchResult.model_validate(old)
    assert r.scorecard.overall_trend == "unclear" and r.scorecard.key_drivers == []
    assert {a.importance for a in r.scorecard.areas} == {"medium"}
    assert {a.trend for a in r.scorecard.areas} == {"unclear"}
    assert r.findings[0].verdict == "unverified" and r.findings[0].also_sources == []
    assert r.profile is None and r.merged == 0
    # and it round-trips once loaded
    assert ResearchResult.model_validate_json(r.model_dump_json()) == r
