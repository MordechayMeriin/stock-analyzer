# Spec Delta

## MODIFIED Requirements

### Requirement: Filing endpoints
The API SHALL list a company's annual filings and indicate, for each fiscal year, which filing was selected as the full report and whether its Markdown is cached. Filing entries SHALL NOT carry document or viewer URLs.

#### Scenario: Selected report flag
- **WHEN** filings for MLTM are requested
- **THEN** filing 32935334 is marked as selected for FY2025

#### Scenario: No document links
- **WHEN** filings for any company are requested
- **THEN** no filing entry has a document URL or viewer URL field

### Requirement: Report endpoints
For a ticker and fiscal year, the API SHALL return the structure tree, the paragraphs of a given node, and the paragraphs of a given page, where a page is a page of the report's Markdown. Each paragraph SHALL include its id, normalized text, page index and printed page (when known). No response SHALL include a link to the source PDF.

#### Scenario: Node paragraphs with citations
- **WHEN** the paragraphs of the risk-factors node are requested
- **THEN** each paragraph includes its id, normalized text, page index and printed page, and no citation URL

#### Scenario: Structure without a document link
- **WHEN** the structure tree of a report is requested
- **THEN** the response has no document URL field

### Requirement: Streaming playground
The API SHALL accept a question plus a ticker, fiscal year and node or page selection, send only that selected report text and the question to the main LLM role, and stream back the Hebrew answer as server-sent events. A final event SHALL carry token usage, cost and the ids of the paragraphs supplied, and no links to the source document.

#### Scenario: Streamed answer
- **WHEN** a question about the risk-factors section is submitted
- **THEN** answer increments arrive as events, followed by a final event with cost and the supplied paragraph ids, and without a citation map

#### Scenario: Oversized selection
- **WHEN** the selected text exceeds the configured context budget
- **THEN** the request is rejected with a clear error asking for a narrower selection
