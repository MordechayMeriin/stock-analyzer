# Report-parsing notes

Findings from checking `parse_md` and `structure` against the full cached reports and the
original PDFs (task 4.7). Each quirk has a regression test; "fixture" means a trimmed slice
in `tests/fixtures/`, "synthetic" a test built from the real line.

| Quirk | Where | Handling | Test |
|---|---|---|---|
| Printed page = Markdown page − 1 (the cover has no number); numbering restarts per chapter | FY2024 / FY2025 | Restarts recorded; the printed/index offset is no longer checked (parser 2: pages are Markdown pages, the PDF is not linked) | fixture + live |
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

## Chapter openers across issuers (structure 2)

Chapters are found from openers in page heads: each page's first content lines, recorded before
any noise stripping. A chapter starts at the first paragraph of its opener's page. The vocabulary
lives in `ingest/vocab.py`.

| Issuer | Chapter opener on the cover | Inner parts that must not start chapters |
|---|---|---|
| Malam | `פרק ראשון` / `פרק שני` … `פרק שביעי` (word ordinals); title on the same or the next line; `פרק ש לישי` (stray space) | `חלק א'` … `חלק ד'` (directors' report parts); running `פרק רביעי לדו"ח תקופתי` on chapter-4 pages |
| El Al | `# פרק א'` with the title on the next line (FY2025); `פרק א' דוח תיאור עסקי התאגיד…` on one line (FY2024); bidi-reversed `ב' פרק …`, `ג ' פרק` (FY2024) | `פרק 1: כללי`, `פרק 2: …`, `פרק 3: …` (digit ordinals); running `פרק א \| תיאור עסקי התאגיד` |
| Rami Levy | `# חלק א'` / `## תיאור עסקי התאגיד` … `חלק ה'` (**חלק** is the chapter word) | `פרק א' - תיאור ההתפתחות…` (the other word); `חלק ב' - מידע אחר`, `חלק ד': …` (the chapter word, on ordinals the main chapters use) |
| Delek | `פרק` alone, title on the next lines (the letter was an image) | `חלק ראשון- …` … `חלק רביעי - …` (the other word) |

Rules:
- A digit ordinal is an inner part.
- The first opener whose title names a chapter fixes the report's chapter word (`פרק`/`חלק`); openers with the other word are inner parts.
- An unnamed title (Malam's `שאלון ממשל תאגידי`, `מכתב הסכמה`) is an "other" chapter only on an ordinal that no main chapter uses and above the last one.
- A page's first head line that starts with a chapter title starts that chapter if it is not found yet. El Al FY2024's additional details open with `פרטים נוספים על התאגיד שם חברה: …`; El Al p36's `פרטים נוספים על התאגיד .` is a sentence end, not a title.
- Separate financial information (`מידע כספי נפרד`, El Al's `פרק ד'`) belongs to the financial statements.

Titles are matched word-aligned on spelling-insensitive keys:
- `דו"ח` = `דוח`, plene and defective spellings agree
- small extraction errors are tolerated (Rami Levy's `פרסים נוספים` for `פרטים נוספים`)
- `תיאור ההתפתחות הכללית של עסקי החברה` does not pass for `תיאור עסקי החברה`

A chapter still missing after all that is located from a chapter header at a page edge: El Al FY2024's garbled governance cover (`ו' ו' דוח שנתי בדבר אפקטיביות ה פ ב ר פ ק …`), with `פרק ו | דוח שנתי בדבר אפקטיביות…` at the foot of the next pages.

## Business TOC and sections across issuers (structure 2)

| Quirk | Where | Handling |
|---|---|---|
| Multi-level TOC numbers (`2.1`, `2.2.1`) were flattened to `21`, `221` | Rami Levy (detailed TOC) | Numbers keep their dots and a level; sections anchor on the shallowest level present |
| A short and a detailed TOC | Rami Levy | Both give the same top-level anchors |
| Every business section numbered under chapter 1: `1.1` … `1.22`, the number inside the title cell (`\| א-279 \| 1.12 הון אנושי \|`) | Delek | Dotted numbers at the TOC's top level; dotted subsections (`1.2.1`) hang under them |
| The section number trails the title and the leading number is the provider's list numbering (`2. כללי. 1.1`) | El Al FY2025 | When several lines carry dotted trailing numbers, the trailing number is the section |
| Dot leaders to the page number (`תחום הפעילות ..........`) | El Al FY2024 | Stripped from TOC titles |
| TOC heading inside another paragraph (`פרק א' - …` / `תוכן עניינים מקוצר`) or in a table's header row (`\| עמוד \| תוכן עניינים \|`) | Rami Levy, Delek | Found through page heads and table header cells |
| Section number alone in the paragraph before the title (`1.1` / `כללי`) or after it (`###### title` / `**6.**`) | Delek, El Al FY2024 | The adjacent number gives the section number and confirms a heading worded unlike its TOC entry (`פרטים שונים` vs `פרטים נוספים`) |
| A Markdown heading marker before the title (`###### title`) | El Al FY2024 | Ignored when matching |
| A generic subsection title at the top of scattered pages (`כללי`) | Delek | Not a running line: running lines also cover 3 consecutive pages |
| Only 8–9 top-level business sections | El Al | Reference check is ≥80% of the report's own top-level TOC entries, not a fixed 10 |

When the TOC matches fewer than `MIN_BUSINESS_SECTIONS` sections and the chapter body has more top-level numbered headings, sections come from body numbering (`business_sections_source` in the coverage).

## Notes and statement sets across issuers (structure 2)

| Quirk | Where | Handling |
|---|---|---|
| Note headings spelled `באור` (defective) with a colon: `באור 2: עיקרי המדיניות החשבונאיות` | Delek | One note pattern over `ביאור`/`באור` with `-`, `–` or `:` (`ingest/vocab.py`) |
| `באור 1: א.` — the note number followed by its first lettered paragraph | Delek | Not taken as the note's title |
| A note heading on a later line of a paragraph (`ביאור 26 - …`) | Rami Levy | Note headings count on every line; statements and auditor headings only on a paragraph's first lines |
| Separate financial information under its standard title `נתונים כספיים מתוך הדוחות הכספיים המאוחדים המיוחסים לחברה` | Delek, El Al | Opens the separate group, like Malam's `מידע כספי נפרד`; its notes restart at 1 |
| Delek's provider text has a heading for only some of its notes (others are merged or garbled, e.g. `### לקוחות - 6: באור 6 - …`) | Delek | Reference check is ≥90% of the note numbers whose heading line appears in the text |
| A further statement set after the notes whose notes restart at 1 | (synthetic; Delek's attached subsidiary statements have English notes) | Becomes `financials-attached-K`; a statement heading followed by a higher note is just a mention |

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

### After chapter detection (parser 2 / structure 2)

```
TICKER FY     PAGES PRINTED  CHAPTERS  SECTIONS     TOC  NOTES STMTS  WARN  MISSING / ERROR
DLEKG  2025     843     197  5/5              0     0/0      0     4     1
ELAL   2024     266     137  5/5              2    2/42     21     4     3
ELAL   2025     275     167  5/5             11   11/40     21     9     1
MLTM   2024     180     163  5/5             22   22/22     40     6     1
MLTM   2025     188     147  5/5             25   25/25     31     8     1
RMLI   2025     250     123  5/5              5    5/29     30     7     3
```

### After business sections (parser 2 / structure 2)

```
TICKER FY     PAGES PRINTED  CHAPTERS  SECTIONS     TOC  NOTES STMTS  WARN  MISSING / ERROR
DLEKG  2025     843     197  5/5             21   21/22      0     4     1
ELAL   2024     266     137  5/5              8     8/8     21     4     2
ELAL   2025     275     167  5/5              8     8/9     21     9     2
MLTM   2024     180     163  5/5             22   22/22     40     6     1
MLTM   2025     188     147  5/5             25   25/25     31     8     1
RMLI   2025     250     123  5/5             29   29/29     30     7     1
```

### After notes and statement sets (parser 2 / structure 2)

```
TICKER FY     PAGES PRINTED  CHAPTERS  SECTIONS     TOC  NOTES STMTS  WARN  MISSING / ERROR
DLEKG  2025     843     197  5/5             21   21/22     17     4     2
ELAL   2024     266     137  5/5              8     8/8     21     5     2
ELAL   2025     275     167  5/5              8     8/9     21     9     2
MLTM   2024     180     163  5/5             22   22/22     40     6     1
MLTM   2025     188     147  5/5             25   25/25     31     8     1
RMLI   2025     250     123  5/5             29   29/29     31     7     1
```

Note coverage (main-set note numbers with a heading line in the text that became note nodes):
Delek 12/12, El Al 21/21 and 19/19, Malam 31/31 and 22/22, Rami Levy 24/24 (NOTES above counts every
note node, separate-set notes included).

### Final (parser 2 / structure 2) — all checks green

```
TICKER FY     PAGES PRINTED  CHAPTERS  SECTIONS     TOC  NOTES STMTS  WARN  MISSING / ERROR
DLEKG  2025     843     197  5/5             21   21/22     17     4     2
ELAL   2024     266     137  5/5              8     8/8     21     5     2
ELAL   2025     275     167  5/5              8     8/9     21     9     2
MLTM   2024     180     163  5/5             22   22/22     40     6     1
MLTM   2025     188     147  5/5             25   25/25     31     8     1
RMLI   2025     250     123  5/5             29   29/29     31     7     1
```

`pytest -m live_data` (tests/unit/test_reference_reports.py) passes for all six: every chapter once,
≥80% of top-level TOC entries matched, ≥90% of note numbers with a heading line found, ≥4 statements.
