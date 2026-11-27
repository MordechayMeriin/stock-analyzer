"""`report` CLI command (analyzer-api spec: report from the CLI) and its parity with the service."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from stock_analyzer.agents_model import FakeAgentModels
from stock_analyzer.cli import app
from stock_analyzer.config import Settings, reset_settings_cache
from stock_analyzer.report.rater import PURPOSE
from stock_analyzer.services import report as report_service
from stock_analyzer.services.context import Ctx
from tests.unit.report_helpers import rater_output, story_run
from tests.unit.test_report_service import ELAL


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    settings = Settings(data_dir=tmp_path)
    ctx = Ctx(settings=settings)
    ctx.store.add_tracked(ELAL)
    ctx.store.save_story_run("ELAL", story_run().model_dump(mode="json"))
    fakes = FakeAgentModels(settings=settings, script={PURPOSE: [rater_output()]})
    monkeypatch.setattr("stock_analyzer.services.story.agent_model_factory", lambda s, store=None: fakes)
    return settings


def test_cached_without_any_report_fails(env):
    # no story report and no stored financials: the ratio fallback has nothing to score
    result = CliRunner().invoke(app, ["report", "ELAL"])
    assert result.exit_code != 0


def test_live_builds_then_cached_prints_the_same_report(env):
    built = CliRunner().invoke(app, ["report", "ELAL", "--live"])
    assert built.exit_code == 0, built.output
    assert json.loads(built.output)["mode"] == "live"

    result = CliRunner().invoke(app, ["report", "ELAL"])
    assert result.exit_code == 0, result.output
    printed = json.loads(result.output)
    service = report_service.company_report(Ctx(settings=env), "ELAL").model_dump(mode="json")
    assert printed == service
