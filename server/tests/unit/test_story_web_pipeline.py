"""The story pipeline with web evidence: the OSINT trigger, live search, saved sources (add-story-web-evidence)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from stock_analyzer.agents_model import FakeAgentModels, tool_call
from stock_analyzer.errors import ResearchInProgress
from stock_analyzer.osint.models import KeptFinding, ResearchResult, Scorecard, SearchHit
from stock_analyzer.osint.search import FakeSearch, SearchResponse
from stock_analyzer.services import osint as osint_service
from stock_analyzer.services.context import Ctx
from stock_analyzer.story.pipeline import StoryRun, latest_run, prepare_story, rerender, stream_story
from tests.unit import test_story_pipeline as story_tests
from tests.unit.test_story_pipeline import AS_OF, pid_of

ctx = story_tests.ctx  # the Malam fixture of the story pipeline tests, shared here

TODAY = datetime.now(UTC).date()
TENDER = 'פורסם 12.10.2026. מלם זכתה במכרז ממשלתי בהיקף 200 מיליון ש"ח.'


def stored_result(
    run_date: date, *, excerpt: str | None = "Published 2026-09-01. Midroog affirmed A1."
) -> ResearchResult:
    finding = KeptFinding(
        claim="Midroog affirmed the rating", signal="positive", confidence="high",
        source_url="https://www.globes.co.il/midroog", source_title="Globes", published_at="2026-09-01",
        derived_from_filing=False, id="F1", area="credit", excerpt=excerpt,
    )  # fmt: skip
    card = Scorecard(
        overall_label="stable", overall_rationale="r", areas=[], risks=[], strengths=[], summary_he="s"
    )
    return ResearchResult(
        ticker="MLTM", company_name="מלם", run_date=run_date, window_months=36,
        window_start=run_date - timedelta(days=3 * 365), model="m", scorecard=card, findings=[finding],
        dropped={}, searches_used=3, search_limit=40, cost_usd=0.05,
    )  # fmt: skip


def seed_stored(ctx: Ctx, run_date: date) -> None:
    key = osint_service.cache_key("MLTM", ctx.settings.osint_window_months)
    ctx.store.cache("llm").set(key, stored_result(run_date).model_dump(mode="json"))


def base_story(prep) -> dict:
    pid = pid_of(prep, 2025)
    return {
        "what_it_does": [
            {"text_he": "מלם תים מספקת שירותי מחשוב; הכנסות {{FIN:revenue:2025}}.", "paragraph_ids": [pid]}
        ],
        "what_changed": [{"text_he": "ההכנסות צמחו ב-{{CHG:revenue:2024-2025}}.", "paragraph_ids": [pid]}],
        "story_vs_numbers": [
            {
                "label": "consistent",
                "text_he": "ההנהלה מתארת צמיחה, והנתונים תומכים: {{CHG:revenue:2024-2025}}.",
                "fact_ids": ["CHG:revenue:2024-2025"],
                "paragraph_ids": [pid],
            }
        ],
    }


def last_output(turn) -> dict:
    return json.loads(turn.tool_outputs()[-1])


def web_story_script(prep) -> list:
    """The storyteller reads stored findings, searches, quotes a number, and cites both."""
    seen: dict[str, str] = {}

    def quote(turn):
        seen["sid"] = last_output(turn)["results"][0]["source_id"]
        return tool_call("quote_web_number", source_id=seen["sid"], text="200 מיליון", unit="money")

    def final(turn):
        web_fact = turn.tool_outputs()[-1].split("}}")[0].removeprefix("{{")
        story = base_story(prep)
        story["what_changed"].append(
            {
                "text_he": f"לאחר פרסום הדוח זכתה החברה במכרז ממשלתי בהיקף {{{{{web_fact}}}}}.",
                "paragraph_ids": [],
                "source_ids": [seen["sid"]],
                "caveat_fact_ids": [web_fact],
            }
        )
        story["story_vs_numbers"][0]["source_ids"] = [seen["sid"]]
        return story

    return [
        tool_call("get_web_findings", area="credit"),
        tool_call("web_search", query="מלם מכרז"),
        quote,
        final,
    ]


def run(prep, settings, script, backend=None) -> list:
    prep.search_backend = backend or FakeSearch(
        script={"מלם מכרז": [SearchHit("https://www.globes.co.il/tender", "Malam wins", TENDER)]}
    )
    return list(stream_story(prep, FakeAgentModels(settings=settings, script={"story.storyteller": script})))


# ---------------------------------------------------------------- 7.1 stored or research


def test_fresh_stored_result_is_used_without_research(ctx, settings):
    seed_stored(ctx, TODAY - timedelta(days=10))
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    assert not prep.osint_needed and prep.osint_stored is not None
    events = run(prep, settings, web_story_script(prep))
    assert events[-1].type == "done", events[-1].message
    messages = [e.message for e in events if e.step == "osint"]
    assert messages[0].startswith("using the stored OSINT result") and not any(
        "started" in m for m in messages
    )
    story: StoryRun = events[-1].data
    assert story.osint.run_date == (TODAY - timedelta(days=10)).isoformat() and not story.osint.started
    assert story.osint.findings == 1


def test_missing_result_starts_a_research_run_beside_the_readers(ctx, settings):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    assert prep.osint_needed
    events = run(prep, settings, web_story_script(prep))
    assert events[-1].type == "done", events[-1].message
    steps = [(e.step, e.message) for e in events]
    started = steps.index(("osint", "OSINT research started for MLTM"))
    first_reader = next(i for i, (s, m) in enumerate(steps) if s == "agent_start")
    storyteller = next(i for i, (s, m) in enumerate(steps) if s == "agent_start" and "storyteller" in m)
    stored_at = next(i for i, (s, m) in enumerate(steps) if m.startswith("OSINT research stored"))
    assert first_reader < started < stored_at < storyteller  # readers start first, the storyteller waits
    assert any(m.startswith("OSINT research area finished") for _, m in steps)
    story: StoryRun = events[-1].data
    assert story.osint.started and story.osint.run_date == TODAY.isoformat() and story.osint.findings > 0
    # stored as the latest OSINT result (under the fake key: fake agents never write a real result)
    assert osint_service.cached_result(ctx, "MLTM", 36, fake=True) is not None
    assert osint_service.cached_result(ctx, "MLTM", 36) is None


def test_stale_result_is_refreshed(ctx, settings):
    seed_stored(ctx, TODAY - timedelta(days=45))
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    assert prep.osint_needed and prep.osint_stored is None


def test_research_in_progress_is_refused_before_any_llm_call(ctx):
    osint_service.acquire_run("MLTM", 36)
    try:
        with pytest.raises(ResearchInProgress):
            prepare_story(ctx, "MLTM", as_of=AS_OF)
    finally:
        osint_service.release_run("MLTM", 36)


def test_fresh_result_does_not_care_about_a_running_research(ctx):
    seed_stored(ctx, TODAY - timedelta(days=1))
    osint_service.acquire_run("MLTM", 36)
    try:
        assert not prepare_story(ctx, "MLTM", as_of=AS_OF).osint_needed
    finally:
        osint_service.release_run("MLTM", 36)


class EmptySearch:
    async def search(self, query, max_results, exclude_domains):
        return SearchResponse(hits=[], summary="", model="fake/search")


def test_failed_research_is_a_warning_and_the_story_goes_on(ctx, settings):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    prep.osint_backend = EmptySearch()  # specialists find nothing: NoFindings
    script = [tool_call("web_search", query="מלם מכרז"), lambda turn: base_story(prep)]
    events = run(prep, settings, script)
    assert events[-1].type == "done", events[-1].message
    story: StoryRun = events[-1].data
    assert any(w.startswith("OSINT research failed") for w in story.warnings)
    assert story.osint.run_date is None and story.searches == ["מלם מכרז"]  # search still worked


# ---------------------------------------------------------------- the storyteller's web evidence


def test_story_cites_web_sources_and_saves_them(ctx, settings):
    seed_stored(ctx, TODAY - timedelta(days=3))
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    events = run(prep, settings, web_story_script(prep))
    assert events[-1].type == "done", events[-1].message
    story: StoryRun = events[-1].data
    assert story.verification[-1].errors == []
    [sid] = story.web_sources
    assert story.web_sources[sid].url == "https://www.globes.co.il/tender"
    assert story.web_sources[sid].excerpts == [TENDER] and story.web_sources[sid].published_at == "2026-10-12"
    web_paragraph = story.rendered.what_changed[1]
    assert web_paragraph.paragraph_ids == [] and web_paragraph.source_ids == [sid]
    fact = next(s for s in web_paragraph.segments if s.type == "fact")
    assert fact.display == "200 מיליון ₪"
    assert "מקור עיתונאי" in web_paragraph.segments[-1].text
    assert story.searches == ["מלם מכרז"]
    assert any(f.kind == "WEB" for f in story.facts)
    assert latest_run(ctx.store, "MLTM").web_sources[sid].excerpts == [TENDER]


def test_saved_story_renders_the_same_after_the_osint_result_is_replaced(ctx, settings):
    seed_stored(ctx, TODAY - timedelta(days=3))
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    story: StoryRun = run(prep, settings, web_story_script(prep))[-1].data
    seed_stored(ctx, TODAY)  # a newer research result replaces the one the story used
    saved = latest_run(ctx.store, "MLTM")
    assert rerender(saved) == saved.rendered == story.rendered
    assert saved.web_sources == story.web_sources


def test_a_run_saved_before_web_evidence_still_loads(ctx, settings):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    story: StoryRun = run(prep, settings, [lambda turn: base_story(prep)])[-1].data
    data = story.model_dump(mode="json")
    for key in ("web_sources", "osint", "searches"):
        data.pop(key)
    for key in ("search_cost_usd", "osint_cost_usd"):
        data["usage"].pop(key)
    for section in ("what_it_does", "what_changed", "story_vs_numbers"):
        for item in [*data["story"][section], *data["rendered"][section]]:
            item.pop("source_ids", None)
    old = StoryRun.model_validate(data)
    assert old.web_sources == {} and old.osint.run_date is None and old.searches == []
    assert rerender(old).what_it_does == story.rendered.what_it_does


# ---------------------------------------------------------------- 7.3 budget, 7.4 reruns


def test_search_allowance_is_in_the_estimate(ctx, settings):
    base = prepare_story(ctx, "MLTM", as_of=AS_OF).estimated_tokens
    more = Ctx(settings.model_copy(update={"story_max_searches": 40}))
    try:
        assert prepare_story(more, "MLTM", as_of=AS_OF).estimated_tokens > base
    finally:
        more.close()


def test_rerun_on_the_same_as_of_replays_searches_and_gives_the_same_story(ctx, settings):
    seed_stored(ctx, TODAY - timedelta(days=3))
    first_backend = FakeSearch(
        script={"מלם מכרז": [SearchHit("https://www.globes.co.il/tender", "Malam wins", TENDER)]}
    )
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    first: StoryRun = run(prep, settings, web_story_script(prep), first_backend)[-1].data
    assert len(first_backend.calls) == 1

    second_backend = FakeSearch()  # would return different hits if it were asked
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    second: StoryRun = run(prep, settings, web_story_script(prep), second_backend)[-1].data
    assert second_backend.calls == []  # served from the search cache
    assert second.story == first.story and second.web_sources == first.web_sources


def test_a_raised_search_limit_changes_the_storyteller_turn_cache_key(ctx, settings):
    from agents import ModelSettings

    from stock_analyzer.agents_model import turn_cache_key
    from stock_analyzer.story.agents import storyteller_agent

    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    sctx = prep.context
    from stock_analyzer.osint.blocklist import load_blocklist
    from stock_analyzer.story.web import StorySearch

    def key(limit: int) -> str:
        sctx.search = StorySearch(
            backend=FakeSearch(), blocklist=load_blocklist("MLTM"), max_searches=limit,
            results_per_search=5, as_of=AS_OF, today=TODAY,
        )  # fmt: skip
        agent = storyteller_agent(sctx, FakeAgentModels(settings=settings))
        return turn_cache_key("m", "sys", "input", ModelSettings(), agent.tools, None, [])

    assert key(20) != key(21)


def test_malam_fits_the_default_budget_with_web_evidence():
    """docs/diff_notes.md measures ~272K tokens of Malam report text; the web allowance (20 searches,
    5 results each, and unknown stored findings) must still fit under the default STORY_MAX_TOKENS."""
    from stock_analyzer.config import Settings
    from stock_analyzer.story.pipeline import web_allowance_tokens

    s = Settings.from_env({})
    allowance = web_allowance_tokens(s, None)
    assert allowance == 84_000  # recorded: Malam needs about 272K + 84K = 356K
    assert 272_000 + allowance < s.story_max_tokens == 1_500_000
