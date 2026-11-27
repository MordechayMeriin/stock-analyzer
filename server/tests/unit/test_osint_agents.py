"""OSINT agents, finding verification and scorecard checks, offline (osint-research spec)."""

from __future__ import annotations

import ast
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from stock_analyzer.osint.agents import NoFindings, fake_model_factory, load_prompt, run_pipeline, tool_name
from stock_analyzer.osint.blocklist import load_blocklist
from stock_analyzer.osint.models import (
    AREA_INFO,
    AREAS,
    AreaAssessment,
    AreaReport,
    Finding,
    Point,
    RunState,
    Scorecard,
    SearchHit,
)
from stock_analyzer.osint.search import FakeSearch
from stock_analyzer.osint.verify import check_scorecard, parse_published, verify_findings
from stock_analyzer.store import StoreLog, get_store

TODAY = date(2026, 11, 26)


def make_state(max_searches: int = 40) -> RunState:
    return RunState(
        ticker="ELAL",
        company_names=["אל על", "El Al Israel Airlines"],
        window_start=date(2025, 11, 26),
        blocklist=load_blocklist("ELAL"),
        max_searches=max_searches,
        results_per_search=5,
    )


def finding(url: str, published: str | None = "2026-10-01", claim: str = "c") -> Finding:
    return Finding(
        claim=claim,
        signal="negative",
        confidence="high",
        source_url=url,
        source_title="t",
        published_at=published,
        derived_from_filing=False,
    )


def log_records(settings):
    path = settings.logs_dir / "llm.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# ---------------------------------------------------------------- prompts


@pytest.mark.parametrize("name", ["specialist", "orchestrator", "synthesizer"])
def test_prompts_load_and_fill(settings, name):
    text = load_prompt(
        settings.prompts_dir,
        name,
        market_context=load_prompt(settings.prompts_dir, "israel_market"),
        company="אל על",
        ticker="ELAL",
        today="2026-11-26",
        window_start="2025-11-26",
        area_name="news",
        area_desc="d",
        tools="- research_news",
    )
    assert "ELAL" in text and "2025-11-26" in text and "$" not in text
    if name != "synthesizer":
        assert "S&P Maalot" in text and "Sector guide" in text  # Israeli market context is included


def test_research_is_not_tied_to_one_company_or_industry(settings):
    """Areas and prompts are generic: the industry comes from the orchestrator's profile of the company."""
    texts = [desc for _, desc in AREA_INFO.values()]
    texts += [load_prompt(settings.prompts_dir, n) for n in ("specialist", "orchestrator", "synthesizer")]
    for text in texts:
        lowered = text.lower()
        for word in ("el al", "elal", "airline", "passenger", "aircraft", "fleet"):
            assert word not in lowered, f"{word!r} in a generic prompt or area description"
    # the sector guide covers the main Israeli sectors, airlines among them
    guide = load_prompt(settings.prompts_dir, "israel_market")
    for sector in (
        "Banks",
        "Insurers",
        "Real estate",
        "Technology",
        "Telecom",
        "Retail",
        "Energy",
        "Defense",
        "Transport",
    ):
        assert sector in guide


# ---------------------------------------------------------------- verification


def test_verify_drops_by_reason_and_assigns_ids():
    state = make_state()
    good = "https://www.globes.co.il/a"
    state.seen_urls = {good: SearchHit(good, "t", "s"), "https://old.example.com/x": SearchHit("u", "t", "s")}
    state.reports = [
        (
            "news",
            AreaReport(
                findings=[
                    finding(good + "/"),  # kept (normalized URL)
                    finding("https://maya.tase.co.il/r/1"),  # blocked
                    finding("https://invented.example.com/a"),  # never returned by a search
                    finding("https://old.example.com/x", published="2024-03-01"),  # outside the window
                    finding(good, published=None, claim="undated"),  # kept, low confidence
                    finding(good + "/"),  # duplicate of the first
                ],
                summary="s",
            ),
        )
    ]
    kept, dropped = verify_findings(state)
    assert [f.id for f in kept] == ["F1", "F2"]
    assert kept[0].area == "news" and kept[0].confidence == "high"
    assert kept[1].confidence == "low" and kept[1].published_at is None
    assert dropped == {"blocked": 1, "not_searched": 1, "outside_window": 1, "unsupported": 0}


def test_parse_published():
    assert parse_published("2026-03-04") == date(2026, 3, 4)
    assert parse_published("2026-02") == date(2026, 2, 28)
    assert parse_published("2025") == date(2025, 12, 31)
    assert parse_published("March 2026") is None and parse_published(None) is None


def _kept():
    state = make_state()
    url = "https://www.globes.co.il/a"
    state.seen_urls = {url: SearchHit(url, "t", "s")}
    state.reports = [
        ("news", AreaReport(findings=[finding(url, claim="a")], summary="s")),
        ("market", AreaReport(findings=[finding(url, claim="b")], summary="s")),
    ]
    return verify_findings(state)[0]


def aa(area, label, ids, trend="deteriorating", importance="high"):
    return AreaAssessment(
        area=area,
        label=label,
        importance=importance,
        assessment="a",
        trend=trend,
        trend_reason="t",
        finding_ids=ids,
    )


def card_with(areas, **kw):
    base = dict(
        overall_label="fragile",
        overall_rationale="r",
        overall_trend="deteriorating",
        overall_trend_reason="t",
        key_drivers=[],
        areas=areas,
        risks=[],
        strengths=[],
        summary_he="ס",
    )
    return Scorecard(**{**base, **kw})


def test_check_scorecard_enforces_citations_and_coverage():
    kept = _kept()  # F1 news, F2 market
    card = Scorecard(
        overall_label="fragile",
        overall_rationale="r",
        overall_trend="deteriorating",
        overall_trend_reason="t",
        key_drivers=[],
        areas=[
            aa("news", "fragile", ["F1", "F9"]),
            aa("market", "stable", []),  # no ids: filled
            aa("labor_government", "watch", ["F1"]),
        ],
        risks=[Point(text=f"r{i}", finding_ids=["F1"]) for i in range(5)]
        + [Point(text="x", finding_ids=["F9"])],
        strengths=[Point(text="s", finding_ids=["F7"])],
        summary_he="ס",
    )
    out = check_scorecard(card, kept)
    by_area = {a.area: a for a in out.areas}
    assert [a.area for a in out.areas] == list(AREAS)
    assert by_area["news"].finding_ids == ["F1"]
    assert by_area["market"].finding_ids == ["F2"]
    assert by_area["labor_government"].label == "insufficient_data"  # no kept finding in that area
    assert by_area["credit"].label == "insufficient_data"
    assert len(out.risks) == 3 and all(p.finding_ids for p in out.risks)
    assert out.strengths == []  # cited nothing that was kept
    assert out.overall_label == "fragile"
    assert by_area["news"].trend == "deteriorating" and by_area["news"].importance == "high"
    assert by_area["labor_government"].trend == "unclear"  # insufficient data: trend forced to unclear
    assert by_area["credit"].trend == "unclear"


def test_check_scorecard_key_drivers():
    from stock_analyzer.osint.models import CompanyProfile, KeyDriver

    kept = _kept()
    profile = CompanyProfile(
        industry="airlines",
        business_lines=["passenger flights"],
        controlling_shareholder=None,
        competitors=[],
        regulator=None,
        key_drivers=["demand", "security", "fuel costs"],
    )
    card = card_with(
        [aa("news", "watch", ["F1"])],
        key_drivers=[
            KeyDriver(driver="Demand", status="positive", explanation="e", finding_ids=["F1", "F9"]),
            KeyDriver(
                driver="security", status="negative", explanation="e", finding_ids=["F9"]
            ),  # unknown id
        ],
    )
    out = check_scorecard(card, kept, profile)
    drivers = {d.driver.lower(): d for d in out.key_drivers}
    assert drivers["demand"].status == "positive" and drivers["demand"].finding_ids == ["F1"]
    assert drivers["security"].status == "unknown" and drivers["security"].finding_ids == []
    assert "fuel costs" not in drivers  # the model's own drivers are kept as given, not padded
    out = check_scorecard(card_with([aa("news", "watch", ["F1"])]), kept, profile)
    assert [d.driver for d in out.key_drivers] == profile.key_drivers  # model named none: profile's, unknown
    assert {d.status for d in out.key_drivers} == {"unknown"}


def test_check_scorecard_counts_also_areas_as_evidence():
    kept = _kept()
    kept[0] = kept[0].model_copy(update={"also_areas": ["competition_macro"]})
    out = check_scorecard(card_with([aa("competition_macro", "watch", ["F1"])]), kept)
    comp = next(a for a in out.areas if a.area == "competition_macro")
    assert comp.label == "watch" and comp.finding_ids == ["F1"]


# ---------------------------------------------------------------- pipeline (fake model, fake search)


def run(settings, state, **kw):
    log = StoreLog(get_store(settings), "llm")
    return asyncio.run(
        run_pipeline(
            settings,
            state,
            backend=kw.pop("backend", FakeSearch()),
            log=log,
            model_factory=kw.pop("factory", fake_model_factory("ELAL")),
            today=TODAY,
        )
    )


def test_orchestrator_calls_every_specialist_and_scorecard_is_cited(settings):
    state = make_state()
    search = FakeSearch()
    out = run(settings, state, backend=search)
    card, kept, dropped = out.scorecard, out.findings, out.dropped
    assert {a for a, _ in state.reports} == set(AREAS)
    assert len(search.calls) == len(AREAS) and state.searches_used == len(AREAS)
    assert len(kept) == 2 * len(AREAS)
    assert dropped == {"blocked": 0, "not_searched": 0, "outside_window": 0, "unsupported": 0}
    assert out.profile is not None and out.profile.key_drivers
    assert {f.verdict for f in kept} == {"supported"}
    assert card.key_drivers and card.overall_trend == "stable"
    assert [a.area for a in card.areas] == list(AREAS)
    ids = {f.id for f in kept}
    assert all(set(a.finding_ids) <= ids and a.finding_ids for a in card.areas)
    assert card.risks and card.strengths


def test_skipped_area_is_researched_directly(settings):
    state = make_state()
    run(settings, state, factory=fake_model_factory("ELAL", skip_areas=("credit",)))
    assert {a for a, _ in state.reports} == set(AREAS)


def test_agent_calls_are_logged(settings):
    run(settings, make_state())
    purposes = {r["purpose"] for r in log_records(settings)}
    assert "osint-agent:osint_orchestrator" in purposes
    assert "osint-agent:osint_synthesizer" in purposes
    assert {f"osint-agent:osint_{a}" for a in AREAS} <= purposes


def test_blocked_results_never_become_findings(settings):
    state = make_state()
    search = FakeSearch(
        script={f"ELAL {a}": [SearchHit("https://maya.tase.co.il/r/1", "filing", "x")] for a in AREAS}
    )
    with pytest.raises(NoFindings):
        run(settings, state, backend=search)
    assert state.seen_urls == {}


def test_search_limit_still_produces_a_scorecard(settings):
    state = make_state(max_searches=2)
    out = run(settings, state)
    card, kept = out.scorecard, out.findings
    assert state.searches_used == 2
    assert kept and {f.area for f in kept} <= set(AREAS)
    assert sum(a.label == "insufficient_data" for a in card.areas) == len(AREAS) - 2


def test_orchestrator_can_profile_the_company_with_search(settings):
    """The orchestrator gets web_search next to the research tools of every area."""
    from stock_analyzer.osint import agents as agents_mod

    seen = {}

    class Spy(agents_mod.FakeAgentModel):
        async def get_response(self, system_instructions, input, model_settings, tools, *args, **kwargs):
            if self.role == "orchestrator":
                seen["tools"] = sorted(t.name for t in tools)
            return await super().get_response(
                system_instructions, input, model_settings, tools, *args, **kwargs
            )

    run(settings, make_state(), factory=lambda role, area: Spy(role, area, "ELAL"))
    assert seen["tools"] == sorted(["web_search", *(tool_name(a) for a in AREAS)])


def test_tool_names_are_stable():
    assert tool_name("news") == "research_news"


# ---------------------------------------------------------------- filing isolation

FORBIDDEN = (
    "stock_analyzer.ingest",
    "stock_analyzer.fin",
    "stock_analyzer.services.reports",
    "stock_analyzer.services.filings",
    "stock_analyzer.services.financials",
    "stock_analyzer.services.ratios",
    "stock_analyzer.services.scorecard",
    "stock_analyzer.tools",
)


def test_osint_code_imports_nothing_from_filing_modules():
    root = Path(__file__).resolve().parents[2] / "stock_analyzer"
    files = [*(root / "osint").glob("*.py"), root / "services" / "osint.py"]
    assert len(files) >= 6
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                assert not name.startswith(FORBIDDEN), f"{path.name} imports {name}"
