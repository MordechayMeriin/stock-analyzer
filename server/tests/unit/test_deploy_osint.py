"""The hosted image and the Render blueprint carry everything OSINT needs (deployment spec)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from stock_analyzer.config import Settings
from stock_analyzer.osint.blocklist import DEFAULT_BLOCKLIST

SERVER = Path(__file__).resolve().parents[2]
REPO = SERVER.parent


def _docker_copies() -> set[str]:
    text = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^COPY\s+(?:--\S+\s+)*(\S+)\s+\S+\s*$", text, re.M)}


def test_image_contains_osint_data_and_prompts():
    copies = _docker_copies()
    blocklist = DEFAULT_BLOCKLIST.relative_to(SERVER).as_posix()
    assert blocklist in copies, f"server/Dockerfile must COPY {blocklist}: OSINT reads it on every run"
    assert "prompts" in copies  # prompts/osint/*.md
    for prompt in ("specialist", "orchestrator", "synthesizer", "verifier", "grouper", "israel_market"):
        assert (SERVER / "prompts" / "osint" / f"{prompt}.md").exists()


def test_dockerignore_keeps_the_blocklist():
    ignore = (SERVER / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "data/*" in ignore and "!data/osint_blocklist.yaml" in ignore


def test_render_blueprint_sets_osint_settings_without_secrets():
    blueprint = yaml.safe_load((REPO / "render.yaml").read_text(encoding="utf-8"))
    api = next(s for s in blueprint["services"] if s["name"] == "stock-analyzer-api")
    env = {e["key"]: e for e in api["envVars"]}
    defaults = Settings()
    assert env["MODEL_OSINT"]["value"] == defaults.model_osint
    assert int(env["OSINT_MAX_SEARCHES"]["value"]) == defaults.osint_max_searches
    assert int(env["OSINT_WINDOW_MONTHS"]["value"]) == defaults.osint_window_months
    assert env["OPENROUTER_API_KEY"] == {"key": "OPENROUTER_API_KEY", "sync": False}  # entered in Render only
