# Tasks

## 1. Scorecard and reference-report harness (measure first)

- [x] 1.1 Add `list_reports() -> list[tuple[str, int]]` to the `Store` protocol, `FsStore` (glob of the raw report directory) and `PgStore` (`select ticker, fiscal_year from stock_analyzer.reports`) per design D11; verify new cases in `tests/unit/test_store_contract.py` pass on the fs parameter (and the pg parameter when `TEST_DATABASE_URL` is set)
- [x] 1.2 Add the `stock-analyzer parse-check [TICKER [FY]]` command (cached mode only). It prints one row per stored report: ticker, FY, pages, pages with a printed number, chapters found/missing, business sections / TOC matches, notes, statements, warning count, parse time. A report that raises gets an error row, and the command exits 1. Verify `tests/unit/test_cli_structure.py` covers a normal row, a missing-chapter row and an error row with exit code 1
- [x] 1.3 Change `tests/conftest.py` so `live_report(ticker, fy)` loads through `get_store(settings)`: a local `DATA_DIR`, or the hosted store when `DATABASE_URL` is set. Add a `REFERENCE_REPORTS` list (MLTM 2024/2025, ELAL 2024/2025, RMLI 2025, DLEKG 2025) and mark absent reports as skipped. Update the `live_data` marker description; existing Malam live tests load through it unchanged. Verify `pytest -m live_data -rs` runs the Malam tests when present and reports clean skips otherwise
- [x] 1.4 Make the six reference reports available to the live tests in the working environment, without new credits where possible: either `DATABASE_URL` pointed at the hosted store, which holds all six, or a seeded local `DATA_DIR`. Run `stock-analyzer parse-check` and record the baseline rows in `server/docs/parsing_notes.md` under a new "Reference reports" section. Verify the table shows Malam complete and the other four reports' gaps (including the Delek crash row)

## 2. Page layer: robustness, footers, running lines, page heads

- [x] 2.1 Fix `_blocks` in `ingest/parse_md.py`: a block whose table start has no later line ending in `|` is emitted as a plain block (design D10). Verify a new trimmed fixture with Delek's unterminated table block parses, and `parse-check DLEKG 2025` no longer shows an error row
- [x] 2.2 Extend `_footer` with the layouts in design D5: a number followed by a running-header line, `- N -`, and a number at the end of a `title | title N` line. Never take a number from a run of table rows. Verify unit tests built from the El Al FY2024 (`49` + `פרק א | …`), Rami Levy (`- 83 -`) and questionnaire-table lines, plus the existing Malam footer tests
- [x] 2.3 Record each page's head: the first six content lines before stripping, excluding image, comment and short Latin-only lines (design D2). Expose it on `ParsedReport.pages`. Verify a fixture with an El Al cover (`ELYAL`, image, `# פרק א'`, `דוח תיאור עסקי התאגיד`) records the Hebrew lines and not the logo line
- [x] 2.4 Detect running lines at page edges with digit-insensitive keys and a new `RUNNING_LINE_MIN_PAGES` setting (default 4, in `config.py` and `.env.example`), per design D4. Remove them from page edges and record each page's `running_header`. Verify a unit test where `פרק א | תיאור עסקי התאגיד` (with and without a trailing number) on five page tops is absent from all paragraphs and present as those pages' running header, while a line on three pages is kept
- [x] 2.5 Remove the PDF-offset machinery (`OffsetIssue`, `OffsetRun`, offset warnings) and keep `numbering_restarts` as pages where the printed number does not increase (design D6). Update the module docstring to say pages are Markdown pages. Update the Malam tests that asserted PDF offsets to assert restarts and printed numbers instead (spec scenario "Consistent offset"). Add a test that El Al FY2025-style footerless pages between consecutive printed numbers produce no warning. Verify `pytest tests/unit/test_parse_md.py` passes
- [x] 2.6 Bump `PARSER_VERSION` to `"2"` and add the new page-layer quirks (unterminated table, footer layouts, running lines, page fragments) to `server/docs/parsing_notes.md`. Verify the full offline suite passes and `parse-check` shows more pages with printed numbers for ELAL 2024 and RMLI 2025 than the baseline

## 3. Vocabulary and chapter detection

- [x] 3.1 Create `ingest/vocab.py` with ordinals (word, letter ± geresh, the `אי` OCR form), chapter words, per-kind chapter title variants, note words, and auditor/statement patterns accepting `דו"ח`/`דו"חות` (design D1). Extend `normalize.match_key` to drop `"` between Hebrew letters. Verify unit tests that `match_key('דו"ח הדירקטוריון') == match_key('דוח הדירקטוריון')` and that every vocabulary title variant classifies to its own kind
- [x] 3.2 Rewrite `find_chapters` to scan page heads only, with the opener grammar and decision rules 1–4 of design D3: digit ordinals are inner, classified titles start chapters, unclassified titles need the report's chapter word plus an increasing ordinal, and opener-less head lines need a full-ratio title match. Verify unit tests for each `report-parsing` scenario: letter ordinals, title on the next line, ordinal lost in extraction (`פרק` alone), `חלק` as the chapter level, spelling/extraction variants, digit-numbered parts, and inner part with an earlier ordinal
- [x] 3.3 Add the running-header fallback for still-missing main chapters (design D3), reported in warnings. Verify a synthetic test where a chapter has no opener but its pages carry its running header
- [x] 3.4 Keep Malam unchanged: verify `tests/unit/test_structure.py` (fixtures and `live_data`) passes without edits to its chapter assertions, and `parse-check MLTM` still shows 5/5 chapters for both years
- [x] 3.5 Bump `STRUCTURE_VERSION` to `"2"` and add the chapter-opener variants per issuer to `server/docs/parsing_notes.md`. Verify `parse-check` shows all five chapters found once for ELAL 2024/2025, RMLI 2025 and DLEKG 2025, and record the rows

## 4. Business sections

- [x] 4.1 Keep dotted TOC numbers and add `TocEntry.level`, so only level-1 entries anchor sections (design D7). Verify a fixture with Rami Levy's short and detailed TOCs yields `כללי` as section 2 and no section 21/22, and the existing Malam TOC tests pass
- [x] 4.2 Add the body-numbering fallback and `Coverage.business_sections_source` (design D8). Show the source in `parse-check` and the CLI structure summary. Verify a synthetic test with no TOC and body headings 1–12 yields twelve sections with source `body_numbering`, and a Malam test asserts source `toc`
- [x] 4.3 Verify `parse-check` shows at least 80% of each reference report's top-level TOC entries matched to business sections, record the rows, and add any new TOC quirks to `server/docs/parsing_notes.md`

## 5. Financial statements

- [ ] 5.1 Make one note-heading pattern over `ביאור`/`באור` with `-`/`–`/`:` separators (design D9). Verify unit tests for `באור 2: עיקרי המדיניות החשבונאית`, `ביאור 1 – כללי`, the existing five Malam layouts, and continuation `(המשך)` lines
- [ ] 5.2 Add attached statement groups: a statement-set heading after the main notes, followed by a note numbered 1, opens `attached-K` with `financials-attached-K-…` ids (design D9). Verify a fixture from Delek's attached-set boundary yields a separate group while the main group's note ids and `note_numbers_missing` are unchanged, and Malam's financial node ids are identical to before
- [ ] 5.3 Verify that at least 90% of the main-group note numbers with a note heading in the text are note nodes, and at least four statements, for every reference report; record the rows, and add the note/statement variants to `server/docs/parsing_notes.md`

## 6. Filing selection

- [ ] 6.1 Require a periodic-report title (`תקופתי`, or case-insensitive `periodic`) in `select.is_candidate` and name the rule in the selection error (design D13). Verify `tests/unit/test_select.py` covers Delek's FY2026 trustee report (no selection; the error lists the filing), the English and Hebrew periodic titles, and the existing Malam cases

## 7. Drop the PDF

- [ ] 7.1 Remove `citation_url` (paragraphs, pages), `document_url` (structure), `document_url`/`viewer_url` (filings) and the playground done event's `citations` from `services/models.py`, `api/schemas.py`, `services/reports.py`, `services/filings.py` and `services/playground.py`. Rename the page route summary to "Markdown page index". Verify the API tests assert the fields are absent and `pytest tests/api` passes
- [ ] 7.2 Regenerate `server/openapi.json` (`scripts/export_openapi.py`) and `web/src/api/schema.d.ts` (`npm run gen:api`). Verify `uv run python scripts/export_openapi.py --check` and `npm run check:api` pass
- [ ] 7.3 Remove PDF links from `ParagraphList.tsx` (page markers show `pageLabel` text only), `ReaderPage.tsx`, `CompanyPage.tsx` and `PlaygroundPage.tsx` (paragraph-id chips without links; keep the "open in reader" link). Update comments that mention citations. Verify `npm run lint` and `npm run build` pass
- [ ] 7.4 Update `web/e2e/ui-check.cjs`: replace the 7.4 PDF-link checks with checks that page markers show printed page numbers and contain no `.pdf` links, and that the playground shows paragraph ids plus the reader link. Verify the script passes against the dev server with cached Malam data
- [ ] 7.5 Remove PDF/citation wording from `README.md`, `server/README.md` and the `web-client` purpose in `openspec/specs/web-client/spec.md` ("reads reports with page citations" → "reads reports with printed page numbers"). Verify `grep -riE "pdf|citation|#page" README.md server/README.md web/src` finds only intended mentions (selection of PDF filings)

## 8. Integration checks

- [ ] 8.1 Add the reference-report test (all five chapters once, ≥80% of top-level TOC entries matched, ≥90% of main-group note numbers with a heading in the text found as notes, ≥4 statements) parametrized over `REFERENCE_REPORTS` as `live_data`. Verify `pytest -m live_data -rs` passes for all six reports with the reports available
- [ ] 8.2 Run the full server checks (`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -rs`) and the web checks (`npm run lint`, `npm run build`, `npm run check:api`). Verify all pass, and that `parse-check` over the store prints six rows with no errors, recorded in `server/docs/parsing_notes.md`

## Workflow follow-up

- Archive the change after review, syncing the `report-parsing`, `filings-client`, `analyzer-api` and `web-client` deltas.
- After deploy, open an El Al, Rami Levy and Delek report in the hosted reader to confirm the trees render without PDF links.
