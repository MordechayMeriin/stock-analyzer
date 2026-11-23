"""Rebuild the trimmed test fixtures from cached reports (task 3.6; generalize-report-parsing D12).

Malam fixtures, from ``server/data/raw/MLTM`` after ``stock-analyzer fetch MLTM 2024 2025``:

    uv run python scripts/make_fixtures.py

Other issuers' layout fixtures, from the state store (``DATA_DIR``, or ``DATABASE_URL``):

    uv run python scripts/make_fixtures.py issuers

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


# Other issuers: (ticker, fiscal year, pages). Style A pages are <!-- page N --> numbers; style B
# pages are 1-based positions in the provider's "---"-separated text, joined into a composite.
ISSUER_SLICES: dict[str, tuple[str, int, list[int]]] = {
    "elal_2025_style_b.md": (
        "ELAL",
        2025,
        [
            1,
            2,  # cover, chapter list
            3,  # business cover: logo OCR, image, "# פרק א'", title on the next line
            4,
            5,
            6,
            7,  # business body pages with the running header "פרק א | תיאור עסקי התאגיד"
            66,  # directors' cover
            78,
            79,
            80,
            81,
            82,  # one printed page (13) split by the provider into four Markdown pages
            120,  # financial statements cover
            218,  # separate financial information cover
            238,  # additional details cover
            272,  # governance cover
        ],
    ),
    "rmli_2025_style_b.md": (
        "RMLI",
        2025,
        [
            2,  # chapter list
            17,  # business cover: "# חלק א'" / "## תיאור עסקי התאגיד" (חלק is the chapter word)
            19,  # short TOC (top-level entries and part rows)
            20,  # detailed TOC (multi-level numbers 2.1, 2.2.1)
            26,  # inner part "פרק א' - תיאור ההתפתחות הכללית של עסקי הקבוצה"
            35,  # inner part "חלק ב' - מידע אחר" (same word as the chapters)
            100,  # inner part "חלק ד': עניינים המשותפים…"
            102,  # footer "- 83 -"
            123,  # directors' cover: "חלק ב'" / 'דו"ח הדירקטוריון'
            141,  # financial statements cover: 'דו"חות כספיים'
            228,  # additional details cover: "פרסים נוספים" (extraction error)
            247,  # governance cover
        ],
    ),
    "dlekg_2025_style_b.md": (
        "DLEKG",
        2025,
        [
            2,  # chapter list
            3,  # business cover: "פרק" alone (the letter was an image), title below
            5,  # "פרק א - תיאור עסקי התאגיד"
            6,  # inner part "חלק ראשון- תיאור ההתפתחות הכללית של עסקי החברה"
            465,  # directors' cover
            507,  # financial statements cover
            801,  # English auditor's report: a "|" table line whose block never closes the pipe
            802,
            818,  # additional details cover
            842,  # governance cover
        ],
    ),
}


def issuers() -> None:
    from stock_analyzer.config import Settings
    from stock_analyzer.store import get_store

    OUT.mkdir(parents=True, exist_ok=True)
    store = get_store(Settings.from_env())
    meta: dict[str, dict] = {}
    for name, (ticker, year, pages) in ISSUER_SLICES.items():
        loaded = store.load_report(ticker, year)
        if loaded is None:
            sys.exit(f"{ticker} FY{year} is not stored (stock-analyzer fetch {ticker} {year})")
        text, report_meta = loaded
        sliced = style_a_slice(text, pages) if "_style_a" in name else style_b_slice(text, pages)
        write(name, sliced)
        meta[name] = {
            "ticker": ticker,
            "fiscal_year": year,
            "filing_id": report_meta.filing_id,
            "pages": pages,
        }
    meta_note = "style_b fixtures are composites: page i in the fixture is source page pages[i-1]"
    write("issuer_fixtures_meta.json", json.dumps({"note": meta_note, "fixtures": meta}, indent=1))
    store.close()


def main() -> None:
    if sys.argv[1:] == ["issuers"]:
        issuers()
        return
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
