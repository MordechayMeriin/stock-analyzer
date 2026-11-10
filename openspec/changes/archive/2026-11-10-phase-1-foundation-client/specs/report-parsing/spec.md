# Spec Delta

## Purpose

Turns a periodic report's provider Markdown into normalized, page-cited paragraphs and a structure tree of chapters, sections, subsections and notes, which every later module reads from.

## ADDED Requirements

### Requirement: Page-style detection
The system SHALL detect which page-marking style a report's Markdown uses: style A (HTML page-comment markers) or style B (pages separated by a `---` line that is not a table divider). If neither style is found, parsing SHALL fail.

#### Scenario: Style A
- **WHEN** the Malam FY2024 Markdown is parsed
- **THEN** style A is detected

#### Scenario: Style B
- **WHEN** the Malam FY2025 Markdown is parsed
- **THEN** style B is detected, and `---` lines inside tables are not treated as page breaks

### Requirement: Page assignment with printed page numbers
Every paragraph SHALL carry its page index in the original document and, when a footer shows one, the printed page number. The page index SHALL equal the page number of the original PDF. Printed numbering may restart at a chapter boundary; each restart SHALL be recorded with its page. Within a numbering run, the offset between printed and index numbers SHALL be checked for consistency, and inconsistencies SHALL be logged with their pages.

#### Scenario: Consistent offset
- **WHEN** the Malam FY2024 report is parsed
- **THEN** the business chapter's printed page numbers are the page index minus 1 (the footer printed 55 is on PDF page 56), later chapters restart their own numbering, and no inconsistency is logged

#### Scenario: Footnote rule is not a page break
- **WHEN** a style B report has a `---` line followed by footnotes, inside a page that has no footer before it
- **THEN** it is not treated as a page break, so page indices keep matching the PDF (Malam FY2025: 188 pages)

### Requirement: Noise stripping
The system SHALL remove page footers, picture-text blocks and lines repeated on more than 30% of pages (a configurable threshold) before splitting the report into paragraphs.

#### Scenario: Repeated page header
- **WHEN** a header line appears on most pages of a style B report
- **THEN** it does not appear in any paragraph

### Requirement: Paragraph records
The text SHALL be split into paragraphs on blank lines, with a whole Markdown table forming one paragraph. Each paragraph SHALL have a stable id built from ticker, fiscal year, page index and sequence, plus its filing id, character span in the source, raw text, normalized text, heading level and a table flag.

#### Scenario: Stable ids
- **WHEN** the same report is parsed twice
- **THEN** it produces identical paragraph ids

#### Scenario: Table paragraph
- **WHEN** a Markdown table spans several lines
- **THEN** it becomes a single paragraph with the table flag set

### Requirement: Hebrew text normalization
Normalized text SHALL have bidi control characters removed, Markdown emphasis and inline HTML (`**`, `<u>`, `<br>`) stripped, Hebrew geresh and gershayim unified with ASCII quotes, HTML entities unescaped, and whitespace collapsed. The same normalization SHALL be used everywhere the system compares text.

#### Scenario: Gershayim variants
- **WHEN** `ש״ח` and `ש"ח` are normalized
- **THEN** both give the same string

### Requirement: Chapter detection
The system SHALL identify the report's chapters (business, directors' report, financial statements, additional details, governance) by their Hebrew title markers, ignoring matches inside the table of contents. Each chapter SHALL be found once; a missing or duplicated chapter SHALL be reported.

#### Scenario: Malam chapters
- **WHEN** the structure of the Malam FY2025 report is built
- **THEN** each of the five chapters is found exactly once, outside the table of contents

### Requirement: TOC-anchored business sections
Business-chapter sections SHALL be located by parsing the report's own table of contents into ordered (number, title) pairs and finding each title in the body in order by fuzzy title match. Section numbers are kept for display only and SHALL NOT be used for matching.

#### Scenario: Numbering mismatch
- **WHEN** the TOC numbers the risk-factors section 25 but the body numbers it 22
- **THEN** the section is still found by its title, and its display number comes from the body

#### Scenario: Minimum coverage
- **WHEN** fewer than 10 business sections are found
- **THEN** a sanity warning is reported along with the coverage figures

### Requirement: Subsection detection
The system SHALL detect numbered subsections in every observed numbering form: `22.1.1. title`, `.22.1.1 title`, `## 22.1.2 title`, `title .22.3.6`, a number alone on its own line, and a title glued to its body text.

#### Scenario: Each numbering form
- **WHEN** fixture lines in each of the six forms are parsed
- **THEN** each yields a subsection with the right number and title

### Requirement: Directors' report and financial statements structure
The directors' report SHALL be split by its lettered headings. The financial-statements chapter SHALL be split into the auditor's report, the primary statements and the numbered notes.

#### Scenario: Notes
- **WHEN** the financial statements of Malam FY2025 are structured
- **THEN** every `ביאור N` heading becomes a note node with its title

### Requirement: Structure tree output
The structure SHALL be a tree of nodes. Each node has an id, kind, chapter, display number, title, normalized title, level, paragraph range, page range and children. The tree SHALL be available from the CLI and the API for a given ticker and fiscal year.

#### Scenario: CLI structure dump
- **WHEN** the CLI `structure MLTM 2025` is run on cached data
- **THEN** the tree is printed with page ranges, followed by a coverage summary
