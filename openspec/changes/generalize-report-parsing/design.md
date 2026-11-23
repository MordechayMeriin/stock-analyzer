# Design

## Context

See proposal.md (Why). The parser has two stages:
- `ingest/parse_md.py`: Markdown → pages → cleaned paragraphs
- `ingest/structure.py`: paragraphs → structure tree

Both were tuned on Malam-Team's FY2024/FY2025 reports. Text-matching vocabulary is scattered as regex literals through `structure.py`: word ordinals only, `ביאור` only, `דוח` only, chapter title markers checked with `startswith`.

The five full reports were run through the current code (El Al FY2024/FY2025, Rami Levy FY2025, Delek FY2025, plus Malam FY2025 as control):

| Report | Chapters found | Business sections | Notes | Notes |
|---|---|---|---|---|
| Malam FY2025 | 5/5 | 25/25 | 31 | control |
| El Al FY2024 | 1 (false) | 0 | 0 | |
| El Al FY2025 | 0 | 0 | 0 | |
| Rami Levy FY2025 | 1 | 5 of 29 TOC | 0 | |
| Delek FY2025 | — | — | — | crash in `parse_md._blocks` |

The root causes behind those numbers drive the decisions below:
- chapter openers: letter ordinals, `חלק` as the chapter word, title on a later line, ordinal lost to an image (`פרק` alone)
- running headers below the 30% threshold
- footer layouts not recognised
- multi-level TOC numbers flattened (`2.1` → `21`)
- `באור`
- an attached statement set
- an unterminated table block

Other constraints:
- Stored reports live in the state store: fs or Postgres, through the `Store` protocol. Structures are recomputed from stored Markdown and memoized on (hash, `PARSER_VERSION`, `STRUCTURE_VERSION`).
- `Store` has no way to list stored reports today.
- Paragraph ids (`TICKER-FY-pNNNN-NNN`) appear in LLM cache keys and playground answers. Malam's ids must not change.

## Goals / Non-Goals

**Goals:**
- One rule set and one vocabulary that cover every reference issuer, so a new issuer's variants are added in one place.
- Chapter detection that tells chapters from inner parts without per-issuer configuration.
- Failures become visible coverage gaps, never crashes or silently empty trees.
- Malam's output (chapters, sections, notes, paragraph ids) is unchanged.

**Non-Goals:**
- Per-issuer profiles or configuration files.
- Splitting directors' reports that use neither lettered headings nor `חלק` parts (not in the reference minimums; reported via coverage only).
- Parsing English-language headings, including notes inside an attached English statement set.
- Merging provider page fragments. With the PDF dropped, a fragment is just a short page.

## Decisions

### D1. One vocabulary module, not issuer profiles

All Hebrew matching vocabulary moves to a new `ingest/vocab.py`:
- ordinals: words, letters `א`–`ט` with an optional `'`/`׳`, and the geresh-read-as-`י` form `אי` seen in Delek's TOC
- chapter words `פרק`/`חלק`
- per chapter kind, a list of title variants, e.g. directors: `דוח הדירקטוריון`, `דו"ח הדירקטוריון`, `דו"ח דירקטוריון`, `דוח הדירקטוריון על מצב ענייני התאגיד`
- note words `ביאור`/`באור`, plus the auditor and statement patterns (also accepting `דו"ח`/`דו"חות`)

`structure.py` imports from it.

`normalize.match_key` additionally drops a `"` between two Hebrew letters (`דו"ח` → `דוח`). Matching keys only; display text is untouched.

*Alternative considered:* a YAML profile per issuer. Rejected: the goal is "any issuer", and profiles fail the next unseen issuer the same way the current code failed El Al. A shared list of variants generalises, and each new variant is one line.

### D2. Page heads are recorded before noise stripping; chapters are found from page heads

`parse_md` records, for each page, its **head**: the first six content lines before any stripping. Image lines, comment lines and short Latin-only lines are excluded; those are logo OCR such as `ELYAL` or `EVALUATION`.

`structure.find_chapters` looks for chapter openers only in page heads, and a chapter starts at the first paragraph of that page.

This has two benefits:
- Chapter detection is independent of running-header removal. A cover title that also occurs as a running header elsewhere can't be stripped before it is seen.
- Mid-page cross-references (`ראו פרק ב'`) can't start chapters.

*Alternative considered:* keep scanning every heading-like paragraph (today's approach). Rejected: it is what lets body lines like `פרק המונופולין בחוק התחרות` and running headers act as openers. Every reference report starts its chapters on a new page.

### D3. Opener grammar and chapter classification

An opener is a page-head line matching `(פרק|חלק) [ordinal] [separator -|–|:|'] [title]`. The ordinal and the title are optional. When the title is missing on the opener line, it is taken from the following head lines: up to three short lines, joined.

The title is classified against D1's variants with `partial_ratio` alignment on match keys and the existing `CHAPTER_MATCH_THRESHOLD` (85). This tolerates one-letter OCR errors (`פרסים נוספים`) and trailing company names. A different title that merely shares words (`תיאור ההתפתחות הכללית של עסקי החברה` against `תיאור עסקי התאגיד`) stays below the threshold.

Decision rules, in order:
1. A digit ordinal (`פרק 1:`) is an inner part, never a chapter.
2. A classified title starts that chapter kind.
   - The kind seen again right after itself is a cover/first-page repeat and is ignored.
   - The kind seen again after another chapter is reported as a duplicate.
   - If the title and the ordinal disagree, the title wins.
3. An unclassified title starts an "other" chapter only when all three hold:
   - its chapter word equals the report's chapter word, i.e. the word used by the first classified opener (`חלק` for Rami Levy, `פרק` for everyone else)
   - it has an ordinal
   - the ordinal is greater than the last chapter ordinal

   Otherwise it is an inner part. This covers Delek's `חלק ראשון …`, Rami Levy's `פרק א' …` and Malam's `חלק א'` directors' parts.
4. A head line with no opener whose whole text matches a chapter title variant (full `ratio` ≥ threshold, not partial) starts that chapter. This catches Delek's directors' report, which opens with a plain `דוח הדירקטוריון על מצב ענייני התאגיד` line. Full ratio rejects `### דוח הדירקטוריון וההנהלה` inside Delek's business chapter (≈77).

**Fallback:** for any main chapter still missing, the first page whose recorded running header (D4) classifies as that kind starts it, provided that page comes after the previous chapter found. Its use is reported in the warnings.

TOC pages stay excluded as today. Pages whose head contains a TOC heading (`תוכן עניינים`, `תוכן העניינים`, `תוכן עניינים מקוצר/מפורט`, `רשימת פרקים`) are TOC pages.

### D4. Running headers from page edges, removed but kept as metadata

After footers are found, `parse_md` counts each normalized line among the first three and last three content lines of every page. Lines are keyed with digits removed, so `פרק א | תיאור עסקי התאגיד 46` matches its numberless form. A key is a running line when all of these hold:
- it appears at page edges on at least `RUNNING_LINE_MIN_PAGES` pages (new setting, default 4)
- it is at most 90 characters
- it is not a table row

Running lines are removed wherever they sit at a page edge. Each page records the running lines removed from its head as `running_header`.

The global 30% rule stays as is, for lines repeated anywhere on the page.

*Alternative considered:* lowering the global threshold. Rejected: it would also delete legitimately repeated body lines, such as recurring table captions, that are not at page edges.

### D5. Footer layouts

`_footer` keeps its "last three non-empty lines" window and learns three more layouts:
- a bare number immediately followed by a line that D4 will treat as a running line, or any line containing `|` with Hebrew letters and no number (El Al FY2024)
- `- N -` (Rami Levy)
- a number at the end of a `title | title N` line

The table-row exclusion stays, and extends to the questionnaire case: a footer number is never taken from a line that is part of a run of table rows.

A footerless page keeps `printed = None`. There is no inference from neighbours.

### D6. Page meaning and removing the PDF

`page_index` stays the Markdown page position, the same splitting as today. So Malam's page indices and paragraph ids are unchanged, and only its documentation changes.

Removed:
- `_check_offsets`' consistency issues (`OffsetIssue`) and their warnings
- `OffsetRun`, since nothing else reads it

Kept: `numbering_restarts`, computed as pages where the printed number does not increase.

API models drop:
- `ParagraphOut.citation_url`
- `PageParagraphsOut.citation_url`
- `StructureOut.document_url`
- `FilingOut.document_url` / `viewer_url`
- the playground done event's `citations`

`services/reports.citation_url` is deleted. The page route's summary becomes "Paragraphs of a page (Markdown page index)".

`ReportMeta.document_url` stays in stored metadata, so there is no store migration. It simply isn't served.

The web removes the links in `ParagraphList`, `ReaderPage`, `CompanyPage` and `PlaygroundPage`. The playground keeps paragraph-id chips and its existing "open in reader" link. `pageLabel` already falls back to `עמוד N בקובץ`.

*Alternative considered:* keep `document_url` on filings as harmless metadata. Rejected per the user's direction to drop the PDF entirely.

### D7. Business TOC: keep levels, top-level anchors

`_parse_toc_row` and `_parse_toc_line` return the number as a dotted string. A cell like `.2` becomes `2`, and `2.1` stays `2.1`. The section-number cell is the one in dotted form or the non-page column; the page column is the integer cell next to the title, as today.

`TocEntry` gains `level` (count of number parts). `parse_business_toc` keeps only level-1 entries for anchoring.

When two TOC pages qualify (short and detailed), both yield the same level-1 list, and the first one before the business chapter is used. Part rows (`חלק א' - …`) are skipped, as today.

### D8. Body-numbering fallback for sections

If fewer than `min_business_sections` sections are matched from the TOC, `find_business_sections` falls back to heading-like paragraphs in the business chapter whose first line starts with a single top-level number (`N.` / `.N` / `N `). Numbers must ascend by steps of 1 to 3, and cross-references are excluded with the existing `_REF_*` guards. The rest of the line becomes the title.

Section node ids keep the `business-N` form. `Coverage` gains `business_sections_source: "toc" | "body_numbering"`.

### D9. Financial statement groups

The note patterns become one alternation over D1's note words, with `-`, `–` or `:` separators and an optional `(המשך)`.

Groups generalise from today's `notes` / `separate` pair:
- After the main notes have started, an auditor heading, a primary-statement heading or a `דוחות כספיים ליום …` heading opens a pending new group.
- If a note numbered 1 then follows, the pending group becomes `attached-K`, with node ids `financials-attached-K-…`.
- `separate` keeps its existing trigger and ids.

The main group's ids are unchanged, so Malam is unaffected. `note_numbers_missing` is computed for the main group only, as today.

### D10. Malformed blocks

In `_blocks`, a block whose table start has no later line ending in `|` is emitted as a plain block (no `max()` over an empty sequence). Any other per-page parsing exception is not caught. The page-style failure stays the only intended parse error, and the scorecard surfaces anything else.

### D11. Scorecard command and listing stored reports

`Store` gains `list_reports() -> list[tuple[str, int]]`:
- the fs backend globs the raw report directory
- the Postgres backend runs `select ticker, fiscal_year from stock_analyzer.reports`

This needs no schema change. The in-flight `deploy-render-supabase-storage` change owns the store; this adds one read-only method to both backends and to the store contract tests.

New CLI command `stock-analyzer parse-check [TICKER [FY]]`:
- cached mode only
- prints one table row per report, plus parse time
- prints error rows for reports that fail
- exits 1 if any report failed

*Alternative considered:* a pytest-only harness. Rejected: the scorecard is also how a newly added company gets checked against the hosted store, from any machine with `DATABASE_URL`, at no credit cost.

### D12. Tests: trimmed fixtures plus store-backed reference tests

- `scripts/make_fixtures.py` cuts small slices from each reference report: El Al covers and running-header pages, Rami Levy `חלק` covers and both TOCs, Delek's `פרק`-alone cover, its `באור` notes, its attached-set boundary and the unterminated table block. They go in `tests/fixtures/` next to Malam's, and unit tests assert each scenario in the specs.
- `live_data` tests read reports through `get_store(settings)`. They run against a local fs `DATA_DIR` or, with `DATABASE_URL`, against the hosted store, which already holds all six reference reports, so running them costs no credits. They are parametrized over the six reference reports and skip the reports that are absent.

### D13. Versions and filing selection

- `PARSER_VERSION` and `STRUCTURE_VERSION` go to `"2"`, so memoized structures are recomputed.
- `select.is_candidate` adds the title rule `תקופתי` or case-insensitive `periodic`.

## Risks / Trade-offs

- **[Malam regression]** The chapter algorithm changes from paragraph scanning to page heads. → Malam's fixture and `live_data` tests stay unchanged and must pass. The scorecard shows Malam's row next to the others.
- **[Over-eager running-line removal]** A real heading repeated at four or more page tops (e.g. `ביאורים לדוחות הכספיים המאוחדים`) gets removed. → Acceptable: such lines carry no structure the tree uses. Note headings carry their own `ביאור N`. Chapter openers are read from page heads before removal (D2).
- **[Fuzzy classification false positive]** An inner title close to a chapter title could start a chapter. → Full-ratio matching for opener-less lines, page-head-only scanning, and duplicate reporting make it visible in the scorecard.
- **[Next unseen issuer]** Four issuers don't prove "every" issuer. → D1 and D11 make each new variant a one-line change found by a scorecard row. The tree degrades through D8 and the D3 fallback instead of going empty.
- **[Delek size]** Delek is 2M characters, 832 pages and about 10k paragraphs, and fuzzy TOC matching scales with TOC × paragraphs. → Parse time is printed per report. If Delek exceeds ~10 s, restrict the TOC search window to the business chapter's paragraphs, which it already is, and cache match keys per paragraph.
- **[Breaking API change]** → The only client is the bundled web app, regenerated and updated in the same change. Render deploys server and web from the same commit.

## Migration Plan

- No data migration. Stored Markdown is reparsed lazily, and the memo keys change with the version bumps.
- Deploy server and web together, as the blueprint already does.
- Regenerate `server/openapi.json` and `web/src/api/schema.d.ts` in the same commit.
- Rollback: revert the commit. Nothing persisted depends on the new format.

## Open Questions

- Whether to show the running header (D4) in the reader as a page caption. It is cosmetic and can be decided after the scorecard is green.
- Directors'-report splitting for issuers whose directors' report uses numbered rather than lettered headings (El Al). It is not in the reference minimums. Decide after seeing scorecard coverage, possibly as a follow-up change.
