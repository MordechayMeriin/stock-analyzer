"""`story` CLI command (company-story spec: story from the CLI) and CLI/API parity."""

from __future__ import annotations

from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from stock_analyzer.agents_model import FakeAgentModels
from stock_analyzer.api.main import create_app
from stock_analyzer.cli import app, render_story
from stock_analyzer.config import Settings, reset_settings_cache
from stock_analyzer.ingest.fr_client import Filing, save_report
from stock_analyzer.services.context import Ctx
from stock_analyzer.story.pipeline import StoryRun, prepare_story
from tests.conftest import fixture_text, seed_malam
from tests.unit.test_story_pipeline import AS_OF, good_story, storyteller_script


@pytest.fixture
def story_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    settings = Settings(data_dir=tmp_path)
    seed_malam(settings)
    for fy, filing_id in ((2023, 63741686), (2024, 63741657)):
        filing = Filing(id=filing_id, title=f"Periodic and annual report for {fy}", fiscal_year=fy)
        save_report(settings, "MLTM", fy, filing, fixture_text(f"mltm_{fy}_business_slice.md"))
    with closing(Ctx(settings)) as ctx:
        prep = prepare_story(ctx, "MLTM", as_of=AS_OF)
    script = storyteller_script(prep, [lambda der: good_story(prep, der)])
    fakes = FakeAgentModels(settings=settings, script={"story.storyteller": script})
    monkeypatch.setattr("stock_analyzer.services.story.agent_model_factory", lambda s, store=None: fakes)
    return settings


def test_story_live_prints_progress_and_the_rendered_story(story_env):
    result = CliRunner().invoke(app, ["story", "MLTM", "--live", "--as-of", "2026-11-26"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "· reports selected: FY2023, FY2024, FY2025" in out
    assert "== מה החברה עושה" in out and "== הסיפור מול המספרים" in out
    assert "4,138 מיליון ₪" in out  # the fact rendered by code
    assert "[עקבי]" in out and "== ציטוטים" in out


def test_story_cached_reads_the_saved_run_and_matches_the_api(story_env):
    CliRunner().invoke(app, ["story", "MLTM", "--live", "--as-of", "2026-11-26"])
    cached = CliRunner().invoke(app, ["story", "MLTM"])
    assert cached.exit_code == 0, cached.output
    with TestClient(create_app(story_env)) as c:
        api = StoryRun.model_validate(c.get("/api/companies/MLTM/story").json())
    assert "\n".join(render_story(api)) in cached.output  # CLI and API show the same saved run


def test_story_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    result = CliRunner().invoke(app, ["story", "MLTM"])
    assert result.exit_code == 1 and "not_cached" in result.output
