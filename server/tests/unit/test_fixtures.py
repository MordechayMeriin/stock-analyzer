"""Fixtures stay small: trimmed slices only, never full reports (task 3.6)."""

import json
import subprocess

from tests.conftest import FIXTURES

PER_FILE = 150_000
TOTAL = 450_000


def test_fixtures_under_budget():
    files = [p for p in FIXTURES.iterdir() if p.is_file()]
    assert files
    for p in files:
        assert p.stat().st_size <= PER_FILE, f"{p.name} exceeds {PER_FILE} bytes"
    assert sum(p.stat().st_size for p in files) <= TOTAL


def test_markdown_fixtures_are_slices():
    a = (FIXTURES / "mltm_2024_style_a.md").read_text(encoding="utf-8")
    b = (FIXTURES / "mltm_2025_style_b.md").read_text(encoding="utf-8")
    meta = json.loads((FIXTURES / "fixtures_meta.json").read_text())
    assert a.count("<!-- page ") == len(meta["style_a_pages"]) < 180
    assert b.count("\n---\n") + 1 == len(meta["style_b_pages"]) < 188


def test_full_reports_not_tracked_by_git():
    out = subprocess.run(
        ["git", "ls-files", "--", "data/raw"], capture_output=True, text=True, cwd=FIXTURES.parent.parent
    )
    assert out.stdout.strip() == ""
