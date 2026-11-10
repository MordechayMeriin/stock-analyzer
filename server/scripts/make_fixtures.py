"""Rebuild the trimmed test fixtures from cached Malam reports (task 3.6).

Run from ``server/`` after ``stock-analyzer fetch MLTM 2024 2025``:

    uv run python scripts/make_fixtures.py

Full documents stay out of git; only these slices are committed. Each slice keeps the
provider's exact text so parser tests exercise real quirks.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from stock_analyzer.ingest.fr_client import read_exact

SERVER = Path(__file__).resolve().parent.parent
RAW = SERVER / "data" / "raw" / "MLTM"
OUT = SERVER / "tests" / "fixtures"
BUDGET_BYTES = 150_000  # per fixture file

# Style A (FY2024): absolute <!-- page N --> markers, so slices keep true page indices.
STYLE_A_PAGES = [*range(1, 11), *range(55, 59)]
# Style B (FY2025): a composite of whole pages joined by the provider's "---" separator.
STYLE_B_PAGES = [
    *range(1, 7),  # cover, board, chapter list, business TOC (TOC says 25 for risk), business start
    *range(56, 65),  # legal proceedings (body §19), risk factors (body §22) incl. the impact table
    *range(65, 68),  # directors' report: chapter page + lettered headings
    *range(83, 91),  # financial statements: chapter page, FS TOC, auditor's report, first statement
    99,
    100,  # notes: ביאור 1 and the bidi-reversed "... - 2 ביאור"
    *range(146, 152),  # chapter 4 + the footnote "---" inside PDF page 150 (md 150/151)
    165,
    184,
    188,  # chapters 5, 6 (internal control), 7
]


def style_a_slice(text: str, pages: list[int]) -> str:
    parts = re.split(r"(<!-- page \d+ -->)", text)
    out: list[str] = []
    for i in range(1, len(parts), 2):
        n = int(re.search(r"\d+", parts[i]).group())
        if n in pages:
            out.append(parts[i] + parts[i + 1])
    return "".join(out)


def style_b_slice(text: str, pages: list[int]) -> str:
    split = text.split("\n---\n")
    return "\n---\n".join(split[n - 1] for n in pages)


def trim_financials(data: dict, years: range) -> dict:
    keep_period = {"fiscal_year", "fiscal_period", "period_start_date", "period_end_date"}
    keep_stmt = {"statement_type", "currency", "currency_mismatch", "source_filing"}
    keep_item = {
        "code",
        "name",
        "statement_type",
        "depth",
        "parent_code",
        "sort_order",
        "value",
        "raw_value",
        "scale",
        "currency",
        "available_at",
        "revisions",
    }
    periods = []
    for p in data["periods"]:
        if p.get("fiscal_year") not in years:
            continue
        period = {k: p.get(k) for k in keep_period}
        period["statements"] = [
            {
                **{k: s.get(k) for k in keep_stmt},
                "line_items": [{k: li.get(k) for k in keep_item if k in li} for li in s["line_items"]],
            }
            for s in p["statements"]
        ]
        periods.append(period)
    return {
        "company_id": data["company_id"],
        "currency": data.get("currency"),
        "period_count": len(periods),
        "periods": periods,
    }


def write(name: str, content: str) -> None:
    path = OUT / name
    path.write_text(content, encoding="utf-8", newline="")
    size = path.stat().st_size
    flag = "OK" if size <= BUDGET_BYTES else "OVER BUDGET"
    print(f"{name}: {size:,} bytes {flag}")
    if size > BUDGET_BYTES:
        sys.exit(1)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    a = read_exact(RAW / "2024.md")
    b = read_exact(RAW / "2025.md")
    write("mltm_2024_style_a.md", style_a_slice(a, STYLE_A_PAGES))
    write("mltm_2025_style_b.md", style_b_slice(b, STYLE_B_PAGES))
    fin = json.loads((RAW / "financials.json").read_text(encoding="utf-8"))
    write(
        "mltm_financials.json",
        json.dumps(trim_financials(fin, range(2021, 2026)), ensure_ascii=False, indent=1),
    )
    meta = {
        "style_a_pages": STYLE_A_PAGES,
        "style_b_pages": STYLE_B_PAGES,
        "source_filings": {"2024": 63741657, "2025": 32935334},
        "note": "style_b is a composite: page index i in the fixture is source page style_b_pages[i-1]",
    }
    write("fixtures_meta.json", json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
