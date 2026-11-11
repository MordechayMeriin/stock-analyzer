import json

import httpx
import respx
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import reset_settings_cache

BASE = "https://api.financialreports.eu"


def test_fetch_saves_reports_financials_and_logs_credits(tmp_path, monkeypatch, fixtures_dir):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FR_API_KEY", "dummy-key")
    reset_settings_cache()
    page = json.loads((fixtures_dir / "malam_filings.json").read_text())
    md = {32935334: "# דוח תקופתי לשנת 2025\n" * 50, 63741657: "<!-- page 1 -->\nדוח 2024\n" * 40}
    with respx.mock(base_url=BASE) as mock:
        mock.get("/filings/").mock(
            return_value=httpx.Response(200, json=page, headers={"X-Credits-Charged": "1"})
        )
        for fid, text in md.items():
            mock.get(f"/filings/{fid}/markdown/").mock(
                return_value=httpx.Response(
                    200, text=text, headers={"X-Total-Chars": str(len(text)), "X-Credits-Charged": "6"}
                )
            )
        fin = mock.get("/companies/6901/financials/").mock(
            return_value=httpx.Response(
                200, json={"company_id": 6901, "periods": []}, headers={"X-Credits-Charged": "40"}
            )
        )
        result = CliRunner().invoke(app, ["fetch", "MLTM", "2024", "2025"])
        assert result.exit_code == 0, result.output
        assert fin.call_count == 2  # with and without revisions
        assert fin.calls[1].request.url.params["include"] == "revisions"

    for fy, fid in ((2025, 32935334), (2024, 63741657)):
        text = (tmp_path / "raw" / "MLTM" / f"{fy}.md").read_text(encoding="utf-8")
        meta = json.loads((tmp_path / "raw" / "MLTM" / f"{fy}.meta.json").read_text())
        assert meta["filing_id"] == fid and meta["total_chars"] == len(text) == len(md[fid])
    assert (tmp_path / "raw" / "MLTM" / "financials.json").exists()
    assert "credits used this run: 93" in result.output  # 1 + 6 + 6 + 40 + 40
    log = [json.loads(line) for line in (tmp_path / "logs" / "fr.jsonl").read_text().splitlines()]
    assert sum(r["credits"] for r in log) == 93
    assert "dummy-key" not in (tmp_path / "logs" / "fr.jsonl").read_text()
    # the file backend keeps exactly the pre-store layout under DATA_DIR
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert {p for p in written if not p.startswith("cache/")} == {
        "raw/MLTM/2024.md",
        "raw/MLTM/2024.meta.json",
        "raw/MLTM/2025.md",
        "raw/MLTM/2025.meta.json",
        "raw/MLTM/financials.json",
        "raw/MLTM/financials_revisions.json",
        "logs/fr.jsonl",
    }
    assert "cache/fr/cache.db" in written  # diskcache's SQLite file


def test_fetch_without_key_explains(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    result = CliRunner().invoke(app, ["fetch", "MLTM", "2025"])
    assert result.exit_code == 1
    assert "FR_API_KEY" in result.output


def test_fetch_refused_when_live_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOW_LIVE", "false")
    reset_settings_cache()
    result = CliRunner().invoke(app, ["fetch", "MLTM", "2025"])
    assert result.exit_code == 1 and "live_disabled" in result.output
