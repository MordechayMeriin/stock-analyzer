# Spec Delta

## MODIFIED Requirements

### Requirement: Company and filing browser
The client SHALL let the user pick a tracked company or search for one, show its annual filings by fiscal year with the selected full report marked and its cached status, and show provider credit usage. Filings SHALL be shown without links to their documents.

#### Scenario: Pick Malam
- **WHEN** the user selects Malam
- **THEN** FY2024 and FY2025 are listed, each with its selected report and cached status, and the credit usage is visible

#### Scenario: No document links
- **WHEN** the filings of any company are shown
- **THEN** no filing has a link that opens its PDF

### Requirement: Report reader
For a chosen company and fiscal year, the client SHALL show the report's structure tree and, when a node is chosen, its paragraphs with page markers. A page marker SHALL show the printed page number when the page has one, and otherwise the page's position in the report file; page markers SHALL NOT link to the source PDF.

#### Scenario: Read a section
- **WHEN** the user opens the risk-factors section of Malam FY2025
- **THEN** its paragraphs are shown with printed page numbers, and no page marker opens a PDF

#### Scenario: Page without a printed number
- **WHEN** a paragraph's page has no printed number
- **THEN** its page marker shows the page's position in the report file, labelled as such

#### Scenario: Deep link
- **WHEN** the user opens a URL that names a company, year and node
- **THEN** the reader opens directly at that node

### Requirement: LLM playground
The client SHALL let the user select a report section (or pages), type a question, and see the Hebrew answer stream in. When the answer finishes, the client SHALL show its cost and the ids of the paragraphs that were supplied as context. For a section selection, it SHALL also link to that section in the reader. No link SHALL open the source PDF.

#### Scenario: Ask about a section
- **WHEN** the user asks a question about the selected risk-factors section
- **THEN** the answer appears incrementally, and on completion the cost, the supplied paragraph ids and a link to the section in the reader are shown

#### Scenario: Cancel
- **WHEN** the user cancels a streaming answer
- **THEN** the stream stops and the partial answer stays visible, marked as cancelled
