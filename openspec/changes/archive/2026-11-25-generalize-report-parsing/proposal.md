# Proposal

## Why

The report parser was built and tuned against Malam-Team's two annual reports, and it fails on every other company. The full annual reports of El Al (FY2024, FY2025), Rami Levy (FY2025) and Delek Group (FY2025) were run through it:
- three produce an empty or near-empty structure tree (0–1 of 5 chapters found, no sections, no notes)
- Delek crashes the parser
- for Delek, report selection also picked a 2-page bond-trustee report as a "FY2026 annual report"

The app is meant to analyse any Israeli listed company, so parsing has to hold for the periodic annual report of any issuer, not just one.

A second cause of fragility is the promise that every paragraph's page equals a page of the source PDF and links to it. The provider sometimes splits one PDF page into several Markdown pages, so El Al FY2025 drifts by 6 pages, Rami Levy by 2 and Delek by about 17. Keeping that mapping right across every filing layout is costly and fragile, and the PDF link adds little to the reader. The PDF is dropped from the product entirely.

## What Changes

- **Generalized chapter detection.** Chapters are recognised from any of the forms seen across issuers:
  - word ordinals (`פרק ראשון`), letter ordinals with or without geresh (`פרק א'`, `פרק א -`, `פרק א |`)
  - `חלק` used as the chapter level (Rami Levy)
  - a chapter title on the line after the opener (cover pages)
  - title spellings `דוח`/`דו"ח`/`דו"חות`, and tolerance for small OCR errors in titles

  Inner parts that look similar must not become chapters: `פרק 1: כללי` inside El Al's business chapter, `חלק ראשון` inside Delek's, `פרק א'` inside Rami Levy's. A chapter opener must sit at the top of a page and carry a recognised chapter title, or come in order with a word or letter ordinal.
- **Running headers.** Lines repeated at the top or bottom of many pages within a chapter (`פרק א | תיאור עסקי התאגיד`) are removed from the text even below the global 30% threshold, and are kept as page metadata that can locate a chapter when no opener is found.
- **More footer layouts.** Page numbers are recognised in the forms seen across issuers:
  - a number followed by a running-header line
  - `- 83 -`
  - a number at the end of a running header

  Numbers inside table cells are not taken as page numbers.
- **Business TOC.** Multi-level TOC numbers (`2.1`, `7.15.5`) keep their dots. Only top-level entries become sections. When a report has both a short and a detailed TOC, the short one anchors the sections.
- **Financial statements.** Notes are recognised as `ביאור N` and `באור N`, with `-`, `–` or `:` separators. An attached second set of statements (for example a subsidiary's, in Delek's report) becomes its own group, like the separate financial information, instead of being silently dropped.
- **Degraded structure instead of empty or crash.** A malformed table line no longer crashes parsing. When the business TOC cannot be matched, top-level numbered headings in the body give the sections.
- **Coverage scorecard.** A CLI command parses every stored report and prints one coverage row per report: chapters, sections, notes and warnings. Each issuer pattern gets a trimmed regression fixture. The full stored reports run as opt-in `live_data` tests, so a fix for one company cannot silently break another.
- **Filing selection.** A year's report must be titled as a periodic report (`דוח תקופתי` / `Periodic ... report`). Other PDFs, such as trustee reports, are not candidates even when they are the largest filing in the year.
- **BREAKING: the PDF is dropped.**
  - Paragraphs no longer carry a citation URL.
  - Structure and filings responses no longer carry document or viewer URLs.
  - The playground's final event no longer carries a citation map.
  - The web client shows no PDF links.

  A page is now a page of the provider's Markdown, not of the PDF. The printed page number from the footer stays, and it is the reference shown to users. The printed/index offset consistency checks are removed.
- **Not included:**
  - LLM-assisted structure detection
  - English-language structure parsing (English sections stay as body text inside their chapter)
  - re-fetching or migrating stored reports (parsing is recomputed from the stored Markdown)
  - interim (quarterly) reports

## Capabilities

### New Capabilities

None. The coverage scorecard belongs to report parsing.

### Modified Capabilities

- `report-parsing`: page meaning changes (Markdown pages, no PDF guarantee, no offset checks). It also gains:
  - running-header and footer layouts
  - generalized chapter detection with the chapter/part distinction
  - multi-level TOC handling and a degraded fallback
  - note spellings and attached statement sets
  - robustness against malformed tables
  - the coverage scorecard
- `filings-client`: annual report selection requires a periodic-report title.
- `analyzer-api`: citation URLs, document URLs and the playground citation map are removed. The page endpoint addresses Markdown pages.
- `web-client`: the reader and playground show printed page numbers and paragraph ids without PDF links, and the purpose statement drops "page citations".

## Impact

- **Server code:**
  - `stock_analyzer/ingest/parse_md.py`: footers, running headers, crash fix, page meaning
  - `stock_analyzer/ingest/structure.py`: chapters, TOC, notes, statement groups, fallback
  - `stock_analyzer/ingest/normalize.py`: matching keys for spelling variants
  - `stock_analyzer/ingest/select.py`: periodic-report title rule
  - `stock_analyzer/services/reports.py`, `services/models.py`, `services/filings.py`, `services/playground.py`, `api/schemas.py`, `api/routers/reports.py`: removed URL fields
  - `stock_analyzer/cli.py`: scorecard command
- **Version bumps:** `PARSER_VERSION` and `STRUCTURE_VERSION` change, so memoized structures are recomputed. Paragraph ids keep their format. Malam's ids stay the same because its page splitting does not change.
- **API contract:** `server/openapi.json` and the generated `web/src/api/schema.d.ts` lose the URL fields. **Breaking** for any client reading `citation_url`, `document_url`, `viewer_url` or `citations`; the only client is our web app, updated in the same change.
- **Web:**
  - `ParagraphList.tsx`, `ReaderPage.tsx`, `CompanyPage.tsx`, `PlaygroundPage.tsx`: links removed
  - `lib/format.ts`: page label wording
- **Tests:**
  - new trimmed fixtures for El Al, Rami Levy and Delek layouts
  - existing Malam fixtures and tests kept, except the PDF-offset assertions
  - `live_data` tests extended to every stored report
- **Data:** no store schema change. `ReportMeta.document_url` stays in stored metadata, but nothing serves it.
