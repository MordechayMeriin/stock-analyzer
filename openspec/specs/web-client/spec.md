# web-client Specification

## Purpose

The Hebrew, right-to-left browser client in which an analyst browses companies and reports, reads reports with page citations, inspects financials and queries the LLM. Later phases add diff, ratio, feed, eval and committee views here.

## Requirements

### Requirement: Hebrew right-to-left interface
The whole interface SHALL be in Hebrew with a right-to-left layout. Numbers, dates, tickers and mixed Hebrew/Latin text SHALL display in the correct direction.

#### Scenario: Mixed-direction text
- **WHEN** a paragraph containing "(AI)" and "34.8%" is displayed
- **THEN** the text reads right to left, and the Latin term and number keep their correct order

### Requirement: Company and filing browser
The client SHALL let the user pick a tracked company or search for one, show its annual filings by fiscal year with the selected full report marked and its cached status, and show provider credit usage.

#### Scenario: Pick Malam
- **WHEN** the user selects Malam
- **THEN** FY2024 and FY2025 are listed, each with its selected report and cached status, and the credit usage is visible

### Requirement: Report reader
For a chosen company and fiscal year, the client SHALL show the report's structure tree and, when a node is chosen, its paragraphs with page markers. Each page marker SHALL link to that page of the original document.

#### Scenario: Read a section
- **WHEN** the user opens the risk-factors section of Malam FY2025
- **THEN** its paragraphs are shown with printed page numbers, and each page link opens the source PDF at that page

#### Scenario: Deep link
- **WHEN** the user opens a URL that names a company, year and node
- **THEN** the reader opens directly at that node

### Requirement: Financials view
The client SHALL show a company's normalized financial line items as a table with one column per fiscal year, grouped by statement, values formatted in the reporting currency, and the currency shown.

#### Scenario: Malam financials
- **WHEN** the user opens the financials view for Malam
- **THEN** income, balance-sheet and cash-flow items are shown per year, with the reporting currency displayed

### Requirement: LLM playground
The client SHALL let the user select a report section (or pages), type a question, and see the Hebrew answer stream in. When the answer finishes, the client SHALL show its cost and links to the paragraphs that were supplied as context.

#### Scenario: Ask about a section
- **WHEN** the user asks a question about the selected risk-factors section
- **THEN** the answer appears incrementally, and on completion the cost and source-paragraph links are shown

#### Scenario: Cancel
- **WHEN** the user cancels a streaming answer
- **THEN** the stream stops and the partial answer stays visible, marked as cancelled

### Requirement: Cached and live mode control
The client SHALL show whether it is in cached or live mode, SHALL let the user switch modes when the server allows live mode, and SHALL disable live mode when the server is cached-only.

#### Scenario: Cached-only server
- **WHEN** the server reports that live mode is disabled
- **THEN** the mode control is locked to cached, with an explanation

### Requirement: Loading, empty and error states
Every view SHALL show a loading state while waiting, an empty state when there is no data, and the API's error message, with a retry action, when a request fails.

#### Scenario: Not cached
- **WHEN** a cached-mode request returns "not cached"
- **THEN** the view explains that the data is not cached and offers to fetch it live if live mode is allowed

### Requirement: Configurable API location
The client SHALL find the API through build-time or runtime configuration and SHALL make no assumption that it is served from the same origin.

#### Scenario: Separate API host
- **WHEN** the client is built with the API base URL set to a different host
- **THEN** all requests go to that host
