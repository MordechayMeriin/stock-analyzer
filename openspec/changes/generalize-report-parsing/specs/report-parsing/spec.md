# Spec Delta

## MODIFIED Requirements

### Requirement: Page assignment with printed page numbers
Every paragraph SHALL carry its page index and, when the page's footer shows one, the printed page number. The page index is the position of the page in the provider's Markdown (pages as split by the detected page style); it is not guaranteed to equal a page of the original PDF, and no link to the PDF is derived from it. Printed numbering may restart at a chapter boundary; each restart SHALL be recorded with its page.

#### Scenario: Consistent offset
- **WHEN** the Malam FY2024 report is parsed
- **THEN** pages carry the printed numbers shown in their footers (the footer printed 55 is on page 56), later chapters restart their own numbering, and each restart is recorded with its page

#### Scenario: Footnote rule is not a page break
- **WHEN** a style B report has a `---` line followed by footnotes, inside a page that has no footer before it
- **THEN** it is not treated as a page break (Malam FY2025: 188 pages)

#### Scenario: Provider splits one printed page
- **WHEN** a style B report has footerless pages between two pages whose printed numbers are consecutive (El Al FY2025: Markdown pages 79-81 before printed page 13 on page 82)
- **THEN** parsing succeeds, the footerless pages carry no printed number of their own, and no page-offset warning is reported

### Requirement: Noise stripping
The system SHALL remove page footers, picture-text blocks and lines repeated on more than 30% of pages (a configurable threshold) before splitting the report into paragraphs. Running headers and footers SHALL also be removed: a line that appears among the first or last lines of a page on several pages is removed from those pages even when it stays below the global threshold.

#### Scenario: Repeated page header
- **WHEN** a header line appears on most pages of a style B report
- **THEN** it does not appear in any paragraph

#### Scenario: Chapter running header
- **WHEN** a report prints `פרק א | תיאור עסקי התאגיד` at the edge of every page of its business chapter (El Al: 56 of 266 pages)
- **THEN** that line does not appear in any paragraph, and the pages it was removed from record it as their running header

### Requirement: Chapter detection
The system SHALL identify the report's chapters (business, directors' report, financial statements, additional details, governance) from chapter openers, ignoring the table of contents. An opener is `פרק` or `חלק`, optionally followed by an ordinal (a word such as `ראשון`, or a letter with or without geresh), with the chapter title on the same line or on one of the next short lines. Each chapter SHALL be found once; a missing or duplicated chapter SHALL be reported.

#### Scenario: Malam chapters
- **WHEN** the structure of the Malam FY2025 report is built
- **THEN** each of the five chapters is found exactly once, outside the table of contents

#### Scenario: Letter ordinals
- **WHEN** a report opens its chapters with `פרק א'`, `פרק ב -` or `פרק ג |` followed by the chapter title
- **THEN** each opener starts the chapter its title names

#### Scenario: Title on the next line
- **WHEN** a cover page holds `# פרק א'` and the next line reads `דוח תיאור עסקי התאגיד`
- **THEN** the business chapter starts on that page

#### Scenario: Ordinal lost in extraction
- **WHEN** a cover page holds `פרק` alone, followed within a few lines by `דוח בדבר אפקטיביות הבקרה הפנימית` (Delek FY2025, where the letter was an image)
- **THEN** the governance chapter starts on that page

#### Scenario: Part used as the chapter level
- **WHEN** a report opens its chapters with `חלק א'` / `## תיאור עסקי התאגיד` and `חלק ב'` / `דו"ח הדירקטוריון` (Rami Levy FY2025)
- **THEN** the business and directors' chapters start at those openers

#### Scenario: Spelling and extraction variants in titles
- **WHEN** a chapter title reads `דו"ח הדירקטוריון`, `דו"חות כספיים` or `פרסים נוספים על התאגיד` (an extraction error for `פרטים`)
- **THEN** it is recognised as the directors', financial statements or additional-details chapter respectively

### Requirement: TOC-anchored business sections
Business-chapter sections SHALL be located by parsing the report's own table of contents into ordered (number, title) pairs and finding each title in the body in order by fuzzy title match. Section numbers are kept for display only and SHALL NOT be used for matching. Multi-level TOC numbers (`2.1`, `7.15.5`) SHALL keep their levels; only top-level entries anchor sections. When the report has both a short and a detailed table of contents, sections are anchored on the top-level entries.

#### Scenario: Numbering mismatch
- **WHEN** the TOC numbers the risk-factors section 25 but the body numbers it 22
- **THEN** the section is still found by its title, and its display number comes from the body

#### Scenario: Minimum coverage
- **WHEN** fewer than 10 business sections are found
- **THEN** a sanity warning is reported along with the coverage figures

#### Scenario: Multi-level TOC
- **WHEN** a detailed TOC lists `כללי .2`, then `שנת התאגדות וצורת התאגדות 2.1` and `תחומי הפעילות של הקבוצה 2.2` (Rami Levy FY2025)
- **THEN** `כללי` is a top-level section numbered 2, and the `2.1`/`2.2` entries do not become top-level sections numbered 21 or 22

### Requirement: Directors' report and financial statements structure
The directors' report SHALL be split by its lettered headings. The financial-statements chapter SHALL be split into the auditor's report, the primary statements and the numbered notes. Note headings SHALL be recognised in both spellings (`ביאור N`, `באור N`) with a `-`, `–` or `:` separator. A further set of statements that restarts note numbering after the first set SHALL form its own group, like the separate financial information, instead of being dropped.

#### Scenario: Notes
- **WHEN** the financial statements of Malam FY2025 are structured
- **THEN** every `ביאור N` heading becomes a note node with its title

#### Scenario: Defective spelling
- **WHEN** a report writes its note headings as `באור 2: עיקרי המדיניות החשבונאית` (Delek FY2025)
- **THEN** each becomes a note node numbered N with its title

#### Scenario: Attached statement set
- **WHEN** the financial-statements chapter holds a second set of statements whose notes restart at 1 (Delek FY2025)
- **THEN** that set becomes its own group with its own notes, and the first set's notes are unaffected

## ADDED Requirements

### Requirement: Page footer layouts
The printed page number SHALL be read from the footer layouts seen across issuers:
- a `site | name | N` line
- a bare number on the last line
- a number followed by a running-header line
- a number wrapped in dashes (`- 83 -`)
- a number at the end of a running-header line

Numbers inside table rows SHALL NOT be taken as page numbers.

#### Scenario: Number above a running header
- **WHEN** a page ends with `49` followed by `פרק א | תיאור עסקי התאגיד` (El Al FY2024)
- **THEN** the page's printed number is 49 and neither line appears in a paragraph

#### Scenario: Dash-wrapped number
- **WHEN** a page ends with `- 83 -` (Rami Levy FY2025)
- **THEN** the page's printed number is 83

#### Scenario: Numbers in a questionnaire table
- **WHEN** the last lines of a page are table rows whose cells hold numbers (a governance questionnaire)
- **THEN** no printed number is taken from them

### Requirement: Chapters versus inner parts
An opener SHALL NOT start a chapter when it numbers an inner part of a chapter: an opener with a digit ordinal (`פרק 1: כללי`), or an opener whose title names no chapter and whose ordinal does not continue the chapter sequence (`חלק ראשון - תיאור ההתפתחות הכללית של עסקי החברה` inside Delek's business chapter, `פרק א' - תיאור ההתפתחות הכללית של עסקי הקבוצה` inside Rami Levy's).

#### Scenario: Digit-numbered parts
- **WHEN** El Al's business chapter contains `פרק 1: כללי`, `פרק 2: ...` and `פרק 3: ...`
- **THEN** no chapter starts at them, and the business chapter continues until the directors' report

#### Scenario: Inner part with an earlier ordinal
- **WHEN** a report whose chapters open with `חלק` has `פרק א' - תיאור ההתפתחות הכללית של עסקי הקבוצה` inside its business chapter
- **THEN** no chapter starts there

### Requirement: Business sections without a matching TOC
When the business chapter's table of contents is missing or matches fewer than the minimum number of sections, the system SHALL take the business sections from top-level numbered headings in the chapter body, in ascending order, and report that the fallback was used.

#### Scenario: Fallback to body numbering
- **WHEN** a business chapter has no parsable TOC but its body has headings `1. ...`, `2. ...` … `12. ...`
- **THEN** twelve sections are produced from those headings, and the coverage summary says the body-numbering fallback was used

### Requirement: Malformed input does not crash parsing
Unexpected Markdown shapes SHALL NOT make parsing fail; they SHALL be treated as plain text and parsing continues. One example is a line that starts with `|` in a block where no line ends with `|`. Only the absence of any page style is a parsing failure.

#### Scenario: Unterminated table line
- **WHEN** a page contains a block whose first line starts with `|` and no line in the block ends with `|`
- **THEN** the block becomes an ordinary paragraph and the rest of the report is parsed (Delek FY2025 parses without error)

### Requirement: Reference reports
The parser SHALL meet these minimums on every reference report: Malam FY2024 and FY2025, El Al FY2024 and FY2025, Rami Levy FY2025, Delek FY2025. The minimums are: each of the five main chapters found exactly once, at least 10 business sections, at least 20 notes in the main statement set, and at least four primary statements. These checks SHALL run as opt-in tests against the stored reports.

#### Scenario: All reference reports pass
- **WHEN** the reference-report tests run with the six reports available
- **THEN** every report meets the minimums

#### Scenario: Reports not available
- **WHEN** the reference-report tests run without the stored reports
- **THEN** they are skipped, and the trimmed fixtures of each issuer layout still run

### Requirement: Coverage scorecard
The CLI SHALL offer a command that parses every stored report (or the ones named) and prints one row per report: ticker, fiscal year, pages, pages with a printed number, chapters found and missing, business sections and TOC matches, notes, statements and warning count. It SHALL exit non-zero when any report fails to parse. It runs on stored data only and spends no provider credits.

#### Scenario: Scorecard over the store
- **WHEN** the scorecard command runs with reports for four companies stored
- **THEN** it prints one row per stored report, and a report that misses a chapter shows it in its row

#### Scenario: Parse failure
- **WHEN** one stored report raises an error during parsing
- **THEN** its row shows the error, the other rows are still printed, and the command exits non-zero
