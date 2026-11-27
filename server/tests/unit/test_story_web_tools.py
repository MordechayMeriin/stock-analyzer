"""The storyteller's web tools: findings, live search, cache, hard limit, web quotes (add-story-web-evidence)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from agents import Agent

from stock_analyzer.agents_model import FakeAgentModel, run_agent, tool_call
from stock_analyzer.errors import StorySearchLimitExceeded
from stock_analyzer.osint.blocklist import load_blocklist
from stock_analyzer.osint.models import SearchHit
from stock_analyzer.osint.search import FakeSearch
from stock_analyzer.store import StoreLog, get_store
from stock_analyzer.story.agents import StoryContext, web_search_description, web_tools
from stock_analyzer.story.facts import FactRegistry
from stock_analyzer.story.reading import ReportLibrary
from stock_analyzer.story.web import SourceLedger, StorySearch
from tests.unit.test_story_web import kept

TODAY = date(2026, 11, 26)


def make_ctx(settings, *, as_of: date = TODAY, limit: int = 3, script=None, store=True) -> StoryContext:
    st = get_store(settings) if store else None
    search = StorySearch(
        backend=FakeSearch(script=script or {}),
        blocklist=load_blocklist("MLTM"),
        max_searches=limit,
        results_per_search=5,
        as_of=as_of,
        today=TODAY,
        store=st,
        log=StoreLog(st, "llm") if st else None,
    )
    ledger = SourceLedger()
    ledger.add_stored(kept("https://www.globes.co.il/rating", "F1", area="credit"))
    ledger.add_stored(kept("https://www.calcalist.co.il/strike", "F2", area="labor_government"))
    return StoryContext(
        settings=settings,
        registry=FactRegistry(currency="ILS"),
        library=ReportLibrary({}),
        years=[2023, 2024, 2025],
        ledger=ledger,
        search=search,
    )


def run_tools(settings, ctx: StoryContext, calls: list, purpose: str = "story.storyteller"):
    """Run an agent with the web tools that makes ``calls`` and then answers; returns tool outputs."""
    turns: list = []
    model = FakeAgentModel(settings, "main", purpose=purpose, script=[*calls, "done"], turns=turns)
    agent = Agent(name="t", instructions="t", tools=web_tools(ctx, purpose), model=model)
    asyncio.run(run_agent(agent, "go", max_turns=len(calls) + 2))
    return [json.loads(o) if o.startswith('{"') else o for o in turns[-1].tool_outputs()]


# ---------------------------------------------------------------- get_web_findings


def test_get_web_findings_returns_one_area(settings):
    ctx = make_ctx(settings)
    [out] = run_tools(settings, ctx, [tool_call("get_web_findings", area="credit")])
    [finding] = out["findings"]
    assert finding["area"] == "credit" and finding["source_id"].startswith("SRC:")
    assert finding["published_at"] == "2026-10-01" and finding["excerpts"]
    assert finding["claim"] and finding["derived_from_filing"] is False


def test_get_web_findings_for_an_empty_area_lists_the_counts(settings):
    [out] = run_tools(settings, make_ctx(settings), [tool_call("get_web_findings", area="market")])
    assert out["findings"] == [] and out["findings_per_area"]["credit"] == 1


# ---------------------------------------------------------------- web_search


HITS = {
    "מלם מכרז": [
        SearchHit(
            "https://www.globes.co.il/tender", "Malam wins", 'פורסם 12.03.2026. מכרז של 200 מיליון ש"ח'
        ),
        SearchHit("https://www.themarker.com/undated", "Malam", "No date in this one."),
        SearchHit("https://www.calcalist.co.il/late", "Late", "Published 2026-11-01. Later news."),
        SearchHit("https://maya.tase.co.il/reports/1", "Filing", "Published 2026-03-01."),  # blocked
    ]
}


def test_search_results_carry_source_ids_dates_and_no_summary(settings):
    ctx = make_ctx(settings, script=HITS)
    [out] = run_tools(settings, ctx, [tool_call("web_search", query="מלם מכרז")])
    assert "summary" not in out and out["searches_left"] == 2 and out["blocked_results"] == 1
    by_url = {r["url"]: r for r in out["results"]}
    assert by_url["https://www.globes.co.il/tender"]["published_at"] == "2026-03-12"
    assert by_url["https://www.themarker.com/undated"]["published_at"] is None  # as_of is today: kept
    assert all(r["source_id"] in ctx.ledger for r in out["results"])
    assert "https://maya.tase.co.il/reports/1" not in by_url


def test_past_as_of_drops_later_and_undated_results(settings):
    ctx = make_ctx(settings, as_of=date(2026, 6, 30), script=HITS)
    [out] = run_tools(settings, ctx, [tool_call("web_search", query="מלם מכרז")])
    assert [r["url"] for r in out["results"]] == ["https://www.globes.co.il/tender"]
    assert out["left_out_after_as_of_or_undated"] == 2


def test_search_is_cached_by_query_and_as_of(settings):
    first = make_ctx(settings, script=HITS)
    run_tools(settings, first, [tool_call("web_search", query="מלם מכרז")])
    assert len(first.search.backend.calls) == 1

    again = make_ctx(settings, script=HITS)  # a rerun on the same as_of
    [out] = run_tools(settings, again, [tool_call("web_search", query="מלם מכרז")])
    assert again.search.backend.calls == [] and out["searches_left"] == 2  # a cache hit still counts
    path = settings.logs_dir / "llm.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records = [r for r in records if r["purpose"] == "story-search"]
    assert [r["cache_hit"] for r in records] == [False, True]

    other = make_ctx(settings, as_of=date(2026, 10, 1), script=HITS)  # a different as_of searches again
    run_tools(settings, other, [tool_call("web_search", query="מלם מכרז")])
    assert len(other.search.backend.calls) == 1


def test_search_limit_counts_and_fails_the_run(settings):
    ctx = make_ctx(settings, limit=2)
    calls = [tool_call("web_search", query=f"q{n}") for n in (1, 2, 3)]
    with pytest.raises(StorySearchLimitExceeded) as raised:
        run_tools(settings, ctx, calls)
    assert raised.value.limit == 2 and raised.value.queries == ["q1", "q2"]
    assert "'q1'; 'q2'" in str(raised.value) and "STORY_MAX_SEARCHES" in str(raised.value)
    assert len(ctx.search.backend.calls) == 2  # the third search never reached the provider


def test_search_count_is_shared_across_agent_runs(settings):
    ctx = make_ctx(settings, limit=3)
    run_tools(settings, ctx, [tool_call("web_search", query="a"), tool_call("web_search", query="b")])
    [out] = run_tools(settings, ctx, [tool_call("web_search", query="c")], purpose="story.storyteller")
    assert out["searches_left"] == 0  # the repair attempt sees what the first attempt used


def test_limit_is_in_the_tool_description(settings):
    tools = {t.name: t for t in web_tools(make_ctx(settings, limit=7), "story.storyteller")}
    assert "You have 7 searches" in tools["web_search"].description
    assert web_search_description(7) != web_search_description(8)  # so the turn cache key changes


def test_no_search_tool_without_live_search(settings):
    ctx = make_ctx(settings)
    ctx.search = None
    assert [t.name for t in web_tools(ctx, "x")] == ["get_web_findings", "quote_web_number"]


# ---------------------------------------------------------------- quote_web_number


def test_quote_from_a_live_excerpt(settings):
    ctx = make_ctx(settings, script=HITS)
    out = run_tools(
        settings,
        ctx,
        [
            tool_call("web_search", query="מלם מכרז"),
            lambda turn: tool_call(
                "quote_web_number",
                source_id=json.loads(turn.tool_outputs()[0])["results"][0]["source_id"],
                text="200 מיליון",
                unit="money",
            ),
        ],
    )
    assert (
        out[1].startswith("{{WEB:") and "200 מיליון ₪" in out[1] and "LOW CONFIDENCE (web_source)" in out[1]
    )


def test_quote_from_a_stored_excerpt(settings):
    ctx = make_ctx(settings)
    stored = ctx.ledger.stored()[0]
    stored.excerpts = ["Maalot cut the rating; debt of NIS 1.2 billion."]
    [out] = run_tools(
        settings,
        ctx,
        [tool_call("quote_web_number", source_id=stored.source_id, text="NIS 1.2 billion", unit="money")],
    )
    assert out.startswith("{{WEB:") and "1,200 מיליון ₪" in out


def test_quote_refuses_a_number_only_in_the_summary(settings):
    ctx = make_ctx(
        settings, script={"q": [SearchHit("https://www.ynet.co.il/a", "t", "Published 2026-03-01.")]}
    )
    # FakeSearch's summary is "Example results for q." and the storyteller never receives it; a number
    # that is not in an excerpt cannot be quoted, whatever the search model wrote
    out = run_tools(
        settings,
        ctx,
        [
            tool_call("web_search", query="q"),
            lambda turn: tool_call(
                "quote_web_number",
                source_id=json.loads(turn.tool_outputs()[0])["results"][0]["source_id"],
                text="300 million",
                unit="number",
            ),
        ],
    )
    assert out[1].startswith("ERROR:") and "does not appear in the excerpt" in out[1]


def test_quote_with_an_unknown_source(settings):
    [out] = run_tools(
        settings,
        make_ctx(settings),
        [tool_call("quote_web_number", source_id="SRC:1", text="5", unit="count")],
    )
    assert out.startswith("ERROR: unknown source id")


# ---------------------------------------------------------------- which agents get web tools


def test_only_the_storyteller_has_web_tools(settings):
    from stock_analyzer.agents_model import FakeAgentModels
    from stock_analyzer.story.agents import change_agent, describe_agent, explain_agent, storyteller_agent

    ctx = make_ctx(settings)
    models = FakeAgentModels(settings=settings)
    web = {"get_web_findings", "quote_web_number", "web_search"}
    for agent in (
        describe_agent(ctx, models),
        change_agent(ctx, models, 1),
        explain_agent(ctx, models, 2025),
    ):
        assert not web & {t.name for t in agent.tools}, agent.name
    assert web <= {t.name for t in storyteller_agent(ctx, models).tools}


def test_storyteller_input_has_a_web_index(settings):
    from stock_analyzer.story.agents import web_index

    ctx = make_ctx(settings, limit=20)
    ctx.as_of, ctx.latest_report_published = TODAY, date(2026, 3, 30)
    text = web_index(ctx, "The OSINT research run is from 2026-11-20.")
    assert "credit: 1" in text and "labor_government: 1" in text and "up to 20 web searches" in text
    assert "published on 2026-03-30" in text and "2026-11-20" in text


def test_storyteller_prompt_describes_the_web_rules(settings):
    from stock_analyzer.story.agents import prompt, prompt_hashes

    text = prompt(settings, "story_storyteller")
    for needle in ("get_web_findings", "web_search", "quote_web_number", "source_ids", "derived_from_filing"):
        assert needle in text
    assert "story_storyteller" in prompt_hashes(settings)
