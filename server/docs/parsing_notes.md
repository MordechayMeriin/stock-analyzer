# Report-parsing notes

Findings from checking `parse_md` and `structure` against the full cached reports and the
original PDFs (task 4.7). Each quirk has a regression test; "fixture" means a trimmed slice
in `tests/fixtures/`, "synthetic" a test built from the real line.

| Quirk | Where | Handling | Test |
|---|---|---|---|
| Printed page = PDF page − 1 (not − 2 as first assumed); numbering restarts per chapter | FY2024 / FY2025 | Offset checked per numbering run; restarts recorded, not flagged | fixture + live |
| A `---` above footnotes inside one page (PDF p150) | FY2025 | Not a page break when followed by a footnote marker and no footer yet; 188 pages = PDF | fixture + synthetic + live |
| Table rows and numbered-list items at a page end look like footers | FY2025 p135, p173 | Table rows next to other rows and bare numbers after a list item are not footers | live |
| Stray space inside a word: `פרק ש לישי` | FY2024 | Chapter ordinals matched with spaces removed | synthetic |
| Number glued to a title: `12.שיווק והפצה`, `15.רכוש קבוע…` | FY2024 | Numbers at the edges of a fuzzy match are trimmed off the window | synthetic |
| Plene/defective spelling: `שירותי`/`שרותי`, `חיסכון`/`חסכון` | FY2024 vs TOC | Matching key drops internal ו/י | synthetic |
| A heading followed by `להלן` ("below") | FY2024 §6, §15 | The cross-reference guard only looks after numbers, not titles | synthetic |
| Heading lost its number: `# פעילות החברה בתחום הקמה…` | FY2025 §10 | Display number inferred from the first subsection (`10.1`) | live |
| TOC numbers ≠ body numbers (TOC 25 → body 22 for risk factors) | FY2025 | Matching by title only; body number displayed | fixture + live |
| Orphan subsection number whose title was lost: `.22.2.3` then `22.2.4. …` | FY2024 | Title left empty (shown as the number) | synthetic |
| Glued subsection title + body with no early `.`/`:` | FY2024 | plan.md rule (first `.`/`:` within 120 chars), else ≤ 60 chars at a word boundary — titles can carry a few body words | synthetic (`glued`) |
| Note headings in five layouts (plain, bold+underline, list item, `N ביאור`, reversed `title - N ביאור`); some notes have no heading at all | FY2024 / FY2025 | All five patterns; gaps reported as `note_numbers_missing` | synthetic + live |
| An auditor-report sentence mentioning "דוח רואה החשבון" | FY2025 | Auditor headings must start with `דוח` | synthetic |
| Brand/footer lines after chapter headings (`MalamTeam`, `www… | … | 0`) | both | Excluded from chapter title hints | synthetic |

## Page layer across issuers (parser 2)

Found by running the parser over El Al, Rami Levy and Delek Group. Pages are Markdown pages: the
PDF is not linked, so page splitting only has to serve noise stripping and display.

| Quirk | Where | Handling | Test |
|---|---|---|---|
| A `\|` line opens a block but no line in it ever closes the pipe (an English auditor's-report row) | Delek FY2025 p801 | The block is plain text, not a table; used to crash `_blocks` | fixture `dlekg_2025_style_b.md` |
| Page number above a running chapter header: `49` then `פרק א \| תיאור עסקי התאגיד` | El Al FY2024 | Both lines are the footer | synthetic |
| Dash-wrapped page number `- 83 -` | Rami Levy FY2025 | Footer layout | synthetic |
| Page number glued to a running header: `פרק א \| תיאור עסקי התאגיד 46` | El Al FY2025 | Footer layout (years are never page numbers) | synthetic |
| Governance questionnaire rows end with numbered cells, and a wrapped row's continuation line ends with `\| 23 \|` without starting with `\|` | El Al FY2025 p265 | Lines of a multi-line table block are never footers | synthetic |
| Running headers on a fifth of the pages (`פרק א \| תיאור עסקי התאגיד` on 56 of 266), below the global 30% rule | El Al, Rami Levy, Delek | Short lines at a page edge (first/last 3 lines) on ≥ `RUNNING_LINE_MIN_PAGES` pages are removed; numbers at the line's ends are ignored when comparing; sentences (ending `.`/`:`) and lone letters never count; footer-consumed lines count too | synthetic |
| Logo OCR at page tops (`ELYAL`, `EVALUATION`, `ELVALIN`) | El Al FY2025 | Kept out of page heads | fixture `elal_2025_style_b.md` |
| One printed page split into several Markdown pages (pages 79-81 have no footer, page 82 prints 13 after 12) | El Al FY2025 (+6 pages), Rami Levy (+2), Delek (~+17) | Accepted: a page is a Markdown page; no offset warnings | synthetic |
| Chapter openers live on cover pages whose lines are also stripped as noise (`פרק` alone on Delek's five covers) | Delek FY2025 | Each page's head (first content lines) is recorded before any stripping | fixture |

## Reference reports

The parser is checked against six full reports (the `REFERENCE_REPORTS` list in `tests/conftest.py`):
Malam FY2024 and FY2025, El Al FY2024 and FY2025, Rami Levy FY2025 and Delek Group FY2025.
`stock-analyzer parse-check` prints one coverage row per stored report; it reads stored data only
and spends no provider credits. `pytest -m live_data` runs the full-report tests against the same
store (`DATA_DIR`, or the Postgres store named by `DATABASE_URL`).

### Baseline (before generalizing, parser 1 / structure 1)

```
TICKER FY     PAGES PRINTED  CHAPTERS  SECTIONS     TOC  NOTES STMTS  WARN  MISSING / ERROR
DLEKG  2025                                                             ERROR ValueError: max() iterable argument is empty
ELAL   2024     266      48  1/5              0     0/0      0     0     4  missing: business, directors, financials, governance
ELAL   2025     275     157  0/5              0     0/0      0     0    68  missing: business, directors, financials, additional, governance
MLTM   2024     180     163  5/5             22   22/22     40     6     1
MLTM   2025     188     147  5/5             25   25/25     31     8     1
RMLI   2025     250      78  1/5              5    5/29      0     0    50  missing: directors, financials, additional, governance
```

### After the page layer (parser 2 / structure 1)

```
TICKER FY     PAGES PRINTED  CHAPTERS  SECTIONS     TOC  NOTES STMTS  WARN  MISSING / ERROR
DLEKG  2025     843     197  2/5              0     0/0      0     0     3  missing: business, additional, governance
ELAL   2024     266     137  1/5              0     0/0      0     0     4  missing: business, directors, financials, governance
ELAL   2025     275     167  0/5              0     0/0      0     0     5  missing: business, directors, financials, additional, governance
MLTM   2024     180     163  5/5             22   22/22     40     6     1
MLTM   2025     188     147  5/5             25   25/25     31     8     1
RMLI   2025     250     123  1/5              5    5/29      0     0     6  missing: directors, financials, additional, governance
```
