"""The rater agent reads the story and the run's facts (company-report spec, design D1)."""

from __future__ import annotations

import asyncio

from stock_analyzer.agents_model import FakeAgentModels, run_agent
from stock_analyzer.report.models import RaterOutput
from stock_analyzer.report.rater import PURPOSE, prompt_hash, rater_agent, rater_input
from tests.unit.report_helpers import rater_output, story_run


def test_prompt_loads(settings):
    assert len(prompt_hash(settings)) == 64


def test_input_has_story_text_and_fact_ids():
    text = rater_input(story_run())
    assert "ההכנסות עלו ל־3,432 מיליון $" in text  # rendered story, numbers filled in
    assert "[consistent] הצמיחה ב־2025 נבעה מקיבולת." in text
    assert "{{RATIO:operating_margin:2025}}" in text  # the facts table
    assert "FIN:cfo:2023" in text and "no value" in text
    assert "2023, 2024, 2025" in text


def test_agent_runs_with_fake_model(settings):
    fakes = FakeAgentModels(settings=settings, script={PURPOSE: [rater_output()]})
    out = asyncio.run(run_agent(rater_agent(settings, fakes), rater_input(story_run()), max_turns=2))
    assert isinstance(out, RaterOutput)
    assert [a.axis_id for a in out.axes][0] == "stability"
    assert fakes.turns[0].purpose == PURPOSE
