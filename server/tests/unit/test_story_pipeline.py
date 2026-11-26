"""Story agents, report selection, budget and the offline pipeline (tasks 6.2-6.4)."""

from __future__ import annotations

import asyncio
import time
from datetime import date

import pytest

from stock_analyzer.agents_model import FakeAgentModels, run_agent, tool_call
from stock_analyzer.errors import StoryReportsMissing, StoryTooLarge
from stock_analyzer.ingest.fr_client import Filing
from stock_analyzer.services.context import Ctx
from stock_analyzer.story.agents import (
    ChangeNotes,
    CompanyProfile,
    ManagementClaims,
    change_agent,
    describe_agent,
    explain_agent,
    explain_input,
    prompt_hashes,
)
from stock_analyzer.story.pipeline import StoryRun, prepare_story, stream_story
from stock_analyzer.story.select import story_reports
from tests.conftest import seed_business_slices, seed_malam

AS_OF = date(2026, 11, 26)


@pytest.fixture
def ctx(settings) -> Ctx:
    seed_malam(settings)  # filings, financials and the FY2025 fixture (with a directors' report)
    seed_business_slices(settings)  # FY2023-FY2025 business slices
    from stock_analyzer.ingest.fr_client import save_report
    from tests.conftest import fixture_text

    # FY2025 back to the full-structure fixture, so one year has a directors' report to explain
    save_report(
        settings,
        "MLTM",
        2025,
        Filing(id=32935334, title="Periodic and annual report for 2025", fiscal_year=2025),
        fixture_text("mltm_2025_style_b.md"),
    )
    c = Ctx(settings)
    yield c
    c.close()


def pid_of(prep, year: int) -> str:
    return next(p for p in prep.context.library.paragraphs if p.startswith(f"MLTM-{year}-"))


def good_story(prep, der: str = "DER:1") -> dict:
    pid = pid_of(prep, 2025)
    return {
        "what_it_does": [
            {"text_he": "מלם תים מספקת שירותי מחשוב; הכנסות {{FIN:revenue:2025}}.", "paragraph_ids": [pid]}
        ],
        "what_changed": [{"text_he": "ההכנסות צמחו ב-{{CHG:revenue:2024-2025}}.", "paragraph_ids": [pid]}],
        "story_vs_numbers": [
            {
                "label": "consistent",
                "text_he": "ההנהלה מתארת צמיחה, ושיעור הרווח הגולמי {{" + der + "}} מהכנסות.",
                "fact_ids": [der],
                "paragraph_ids": [pid],
            }
        ],
    }


# ---------------------------------------------------------------- 6.3 selection and budget


def filings() -> list[Filing]:
    import json

    from tests.conftest import FIXTURES

    data = json.loads((FIXTURES / "malam_filings.json").read_text(encoding="utf-8"))
    return [Filing.model_validate(f) for f in data["results"]]


def test_default_as_of_takes_the_three_latest_years():
    assert [y for y, _ in story_reports(filings(), AS_OF, ticker="MLTM")] == [2023, 2024, 2025]


def test_a_report_published_after_as_of_is_excluded():
    with pytest.raises(StoryReportsMissing, match="FY2022"):
        story_reports(filings(), date(2026, 1, 1), ticker="MLTM")  # FY2025 came out in March 2026


def test_not_enough_reports_names_the_missing_years():
    with pytest.raises(StoryReportsMissing, match="FY2023"):
        story_reports([f for f in filings() if f.fiscal_year != 2023], AS_OF, ticker="MLTM")


def test_over_budget_is_refused_before_any_llm_call(ctx, settings):
    small = Ctx(settings.model_copy(update={"story_max_tokens": 1000}))
    with pytest.raises(StoryTooLarge, match="1,000-token budget"):
        prepare_story(small, "MLTM", as_of=AS_OF)
    small.close()


def test_prepare_selects_reports_and_builds_inputs(ctx):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    assert prep.years == [2023, 2024, 2025]
    assert prep.filing_ids == {2023: 63741686, 2024: 63741657, 2025: 32935334}
    assert "FIN:revenue:2025" in prep.context.registry
    assert set(prep.explain_texts) == {2025}  # only the FY2025 fixture has a directors' report
    assert 0 < prep.estimated_tokens <= ctx.settings.story_max_tokens


# ---------------------------------------------------------------- 6.2 reader agents


def test_unchanged_sections_never_reach_a_change_agent(ctx):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    parents = {s.parent for s in prep.comparison.sections if s.level == 3}
    leaves = [s for s in prep.comparison.sections if s.level == 3 or s.key not in parents]
    unchanged = [(s, p) for s in leaves for p in s.pairs if p.status == "unchanged"]
    changed = [(s, p) for s in leaves for p in s.pairs if p.status != "unchanged"]
    assert unchanged and changed, "the slices have both"
    text = "\n".join(prep.change_texts)
    for s, p in unchanged:
        assert f"({s.key}) FY{p.from_year} → FY{p.to_year}" not in text
    for s, p in changed:
        assert f"({s.key}) FY{p.from_year} → FY{p.to_year}: {p.status}" in text


def test_reader_agents_run_their_tools_and_validate(ctx, settings):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    sctx = prep.context
    pid = pid_of(prep, 2025)
    fakes = FakeAgentModels(
        settings=settings,
        script={
            "story.describe": [
                tool_call("read_section", fiscal_year=2025, node_id="business-19"),
                {"items": [{"topic": "business_line", "text_he": "שירותי מחשוב", "paragraph_ids": [pid]}]},
            ],
            "story.change.1": [
                tool_call(
                    "quote_number", paragraph_id=pid, text="x", unit="number"
                ),  # refused, agent continues
                {"notes": []},
            ],
            "story.explain.2025": [{"claims": []}],
        },
    )

    async def run_all():
        profile = await run_agent(describe_agent(sctx, fakes), prep.describe_text, max_turns=4)
        notes = await run_agent(change_agent(sctx, fakes, 1), prep.change_texts[0], max_turns=4)
        claims = await run_agent(explain_agent(sctx, fakes, 2025), prep.explain_texts[2025], max_turns=4)
        return profile, notes, claims

    profile, notes, claims = asyncio.run(run_all())
    assert isinstance(profile, CompanyProfile) and isinstance(notes, ChangeNotes)
    assert isinstance(claims, ManagementClaims)
    describe_turns = [t for t in fakes.turns if t.purpose == "story.describe"]
    assert describe_turns[0].tools == ["quote_number", "read_section", "read_paragraphs"]
    assert "הליכים משפטיים" in describe_turns[1].tool_outputs()[0]  # the real section text came back
    change_turns = [t for t in fakes.turns if t.purpose == "story.change.1"]
    assert change_turns[1].tool_outputs()[0].startswith("ERROR:")


def test_explain_input_is_directors_part_a(ctx):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    text = explain_input(prep.context, 2025)
    assert text is not None and "דוח הדירקטוריון" in text


def test_prompt_files_are_hashed(settings):
    hashes = prompt_hashes(settings)
    assert set(hashes) == {
        "story_rules",
        "story_describe",
        "story_change",
        "story_explain",
        "story_storyteller",
    }
    assert all(len(h) == 64 for h in hashes.values())


# ---------------------------------------------------------------- 6.4 pipeline


def derived_id(turn) -> str:
    """The DER id the derive tool returned to the storyteller, e.g. from "{{DER:123}}  share: ..."."""
    import re

    found = [m.group(1) for out in turn.tool_outputs() if (m := re.search(r"\{\{(DER:\d+)\}\}", out))]
    # never let StopIteration escape: inside a coroutine it becomes an obscure RuntimeError
    assert found, "this turn has no derive result"
    return found[-1]


def storyteller_script(prep, finals: list) -> list:
    """get_facts, derive, then each final story (a dict, or a function of the derived id)."""

    def final(entry):
        return (lambda turn: entry(derived_id(turn))) if callable(entry) else entry

    return [
        tool_call("get_facts", codes=["revenue"], fiscal_years=[2025]),
        tool_call("derive", op="share", fact_ids=["FIN:gross_profit:2025", "FIN:revenue:2025"]),
        *[final(f) for f in finals],
    ]


def run_events(prep, fakes):
    return list(stream_story(prep, fakes))


def test_offline_pipeline_produces_a_verified_story(ctx, settings):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    fakes = FakeAgentModels(
        settings=settings,
        script={"story.storyteller": storyteller_script(prep, [lambda der: good_story(prep, der)])},
    )
    started = time.perf_counter()
    events = run_events(prep, fakes)
    elapsed = time.perf_counter() - started

    assert elapsed < 5
    steps = [e.step for e in events]
    assert steps[0] == "reports" and events[-1].type == "done"
    assert "agent_start" in steps and "tool" in steps and "verify" in steps
    assert steps.index("verify") > steps.index("agent_start")
    run: StoryRun = events[-1].data
    assert run.years == [2023, 2024, 2025] and len(run.verification) == 1 and run.verification[0].errors == []
    fact = next(s for s in run.rendered.what_it_does[0].segments if s.type == "fact")
    assert fact.display == "4,138 מיליון ₪"
    assert any(f.kind == "DER" for f in run.facts)  # the derived fact is saved with the run
    pid = pid_of(prep, 2025)
    assert run.citations[pid].fiscal_year == 2025
    assert run.citations[pid].node_id  # the reader can open the section holding it
    assert run.models == {"reader": settings.model_cheap, "writer": settings.model_main}
    assert set(run.prompt_hashes) >= {"story_describe", "story_storyteller"} and run.config_hash
    assert any("FY2023" in w for w in run.warnings)  # no directors' report in the FY2023 slice


def test_repair_turn_fixes_the_story(ctx, settings):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)

    seen: dict[str, str] = {}

    def bad(der):
        seen["der"] = der  # the repair run is a fresh agent run: it reuses the id derived in attempt 1
        story = good_story(prep, der)
        story["what_it_does"][0]["text_he"] = "הכנסות {{FIN:revenue:2031}}."
        return story

    # attempt 1 ends with the bad story; the repair run (a fresh agent run) answers directly
    script = [*storyteller_script(prep, [bad]), lambda turn: good_story(prep, seen["der"])]
    fakes = FakeAgentModels(settings=settings, script={"story.storyteller": script})
    events = run_events(prep, fakes)
    run: StoryRun = events[-1].data
    assert events[-1].type == "done", events[-1].message
    assert [len(a.errors) for a in run.verification] == [1, 0]
    repair_turn = [t for t in fakes.turns if t.purpose == "story.storyteller"][-1]
    assert "Errors to fix" in str(repair_turn.input) and "FIN:revenue:2031" in str(repair_turn.input)


def test_failed_repair_ends_in_an_error(ctx, settings):
    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    bad = good_story(prep)
    bad["what_it_does"][0]["text_he"] = "הכנסות של 4.1 מיליארד."
    fakes = FakeAgentModels(
        settings=settings, script={"story.storyteller": storyteller_script(prep, [bad, bad])}
    )
    events = run_events(prep, fakes)
    assert events[-1].type == "error" and "failed verification" in events[-1].message
    assert not any(e.type == "done" for e in events)


# ---------------------------------------------------------------- 7.3 saved runs


def test_verified_run_is_saved_and_reads_back_unchanged(ctx, settings):
    from stock_analyzer.story.pipeline import latest_run

    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    script = storyteller_script(prep, [lambda der: good_story(prep, der)])
    events = run_events(prep, FakeAgentModels(settings=settings, script={"story.storyteller": script}))
    run: StoryRun = events[-1].data
    assert any(e.step == "saved" for e in events)
    saved = latest_run(ctx.store, "MLTM")
    assert saved.model_dump(mode="json") == run.model_dump(mode="json")


def test_failed_run_saves_nothing(ctx, settings):
    from stock_analyzer.errors import NotCached
    from stock_analyzer.story.pipeline import latest_run

    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    bad = good_story(prep)
    bad["what_it_does"][0]["text_he"] = "הכנסות של 4.1 מיליארד."
    events = run_events(
        prep,
        FakeAgentModels(
            settings=settings, script={"story.storyteller": storyteller_script(prep, [bad, bad])}
        ),
    )
    assert events[-1].type == "error"
    with pytest.raises(NotCached):
        latest_run(ctx.store, "MLTM")


def test_saved_story_keeps_its_numbers_after_a_provider_revision(ctx, settings):
    import json

    from stock_analyzer.story.pipeline import latest_run, rerender
    from tests.conftest import FIXTURES, seed_fr_cache

    prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    script = storyteller_script(prep, [lambda der: good_story(prep, der)])
    run_events(prep, FakeAgentModels(settings=settings, script={"story.storyteller": script}))

    # the provider revises FY2025 revenue
    data = json.loads((FIXTURES / "mltm_financials.json").read_text(encoding="utf-8"))
    for period in data["periods"]:
        if period["fiscal_year"] == 2025:
            for statement in period["statements"]:
                for item in statement["line_items"]:
                    if item["code"] == "revenue":
                        item["value"], item["raw_value"] = (
                            "5000000000.00",
                            "5000000000.000000",
                        )  # scale: units
    seed_fr_cache(settings, "/companies/6901/financials/", {"fiscal_period": "FY"}, data)
    assert (
        prepare_story(ctx, "MLTM", as_of=AS_OF).context.registry.get("FIN:revenue:2025").value == "5000000000"
    )

    saved = latest_run(ctx.store, "MLTM")
    fact = next(s for s in saved.rendered.what_it_does[0].segments if s.type == "fact")
    assert fact.display == "4,138 מיליון ₪"  # what the story was written with
    assert rerender(saved) == saved.rendered  # rendering again uses the saved facts, not current data
