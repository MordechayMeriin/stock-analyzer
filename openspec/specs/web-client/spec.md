# web-client Specification

## Purpose

The Hebrew, right-to-left browser client in which an analyst browses companies and reports, reads reports with printed page numbers, inspects financials and queries the LLM. Later phases add diff, ratio, feed, eval and committee views here.

## Requirements

### Requirement: Hebrew right-to-left interface
The whole interface SHALL be in Hebrew with a right-to-left layout. Numbers, dates, tickers and mixed Hebrew/Latin text SHALL display in the correct direction.

#### Scenario: Mixed-direction text
- **WHEN** a paragraph containing "(AI)" and "34.8%" is displayed
- **THEN** the text reads right to left, and the Latin term and number keep their correct order

### Requirement: Company and filing browser
The client SHALL let the user pick a tracked company or search for one, show its annual filings by fiscal year with the selected full report marked and its cached status, and show provider credit usage. Filings SHALL be shown without links to their documents. A year whose selected report is not cached and whose Markdown the provider has not processed or could not convert SHALL be shown as unavailable, with the reason, and without actions to read the report or ask about it.

#### Scenario: Pick Malam
- **WHEN** the user selects Malam
- **THEN** FY2024 and FY2025 are listed, each with its selected report and cached status, and the credit usage is visible

#### Scenario: No document links
- **WHEN** the filings of any company are shown
- **THEN** no filing has a link that opens its PDF

#### Scenario: Report waiting for the provider
- **WHEN** the user opens Rami Levy and FY2024's selected report is not cached and has Markdown availability `processing`
- **THEN** FY2024 is marked as not yet processed by the provider, explains that its text is not available yet, and offers no action to read it or ask about it

#### Scenario: Report the provider could not convert
- **WHEN** a year's selected report is not cached and has Markdown availability `failed`
- **THEN** the year is marked as one the provider could not convert, and offers no action to read it or ask about it

#### Scenario: Cached report stays readable
- **WHEN** a year's selected report is cached, whatever its Markdown availability
- **THEN** the actions to read it and ask about it are offered

#### Scenario: Unknown availability
- **WHEN** a year's selected report is not cached and has Markdown availability `unknown` or `available`
- **THEN** the actions to read it and ask about it are offered, as today

### Requirement: Track a company from search
For each provider search result that is not tracked, the client SHALL offer an action to add it. The action SHALL open a form with the ticker and Hebrew name prefilled from the result and editable, and SHALL require both before submitting. After a successful add, the tracked-companies list and the search result SHALL show the company as tracked without a page reload.

#### Scenario: Add from search
- **GIVEN** the client is in live mode
- **WHEN** the user searches, chooses "add to tracking" on an untracked result, and submits the form
- **THEN** the company appears in the tracked-companies list, and the search result links to it instead of showing "not tracked"

#### Scenario: Provider gives no ticker
- **WHEN** the user opens the add form for a result without a ticker
- **THEN** the ticker field is empty and the form cannot be submitted until a ticker is entered

#### Scenario: Add refused
- **WHEN** the server refuses the add, for example because the ticker is already tracked
- **THEN** the form stays open and shows the API's error message

### Requirement: Stop tracking an added company
The client SHALL offer a "stop tracking" action only on companies whose source is `added`, SHALL ask for confirmation, and after a successful removal SHALL drop the company from the tracked-companies list without a page reload.

#### Scenario: Remove an added company
- **GIVEN** the client is in live mode and ABC was added at runtime
- **WHEN** the user chooses "stop tracking" on ABC and confirms
- **THEN** ABC disappears from the tracked-companies list

#### Scenario: Version-controlled company
- **WHEN** the tracked-companies list shows MLTM
- **THEN** no "stop tracking" action is offered for it

### Requirement: Tracking actions need live mode
In cached mode, the client SHALL show the add and stop-tracking actions as disabled, with an explanation that they need live mode. When the server is cached-only, that explanation SHALL say that live mode is turned off on the server.

#### Scenario: Cached mode
- **WHEN** the client is in cached mode and shows an untracked search result
- **THEN** its add action is disabled and explains that live mode is needed

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

### Requirement: Financials view
The client SHALL show a company's normalized financial line items as a table with one column per fiscal year, grouped by statement, values formatted in the reporting currency, and the currency shown.

#### Scenario: Malam financials
- **WHEN** the user opens the financials view for Malam
- **THEN** income, balance-sheet and cash-flow items are shown per year, with the reporting currency displayed

### Requirement: LLM playground
The client SHALL let the user select a report section (or pages), type a question, and see the Hebrew answer stream in. When the answer finishes, the client SHALL show its cost and the ids of the paragraphs that were supplied as context. For a section selection, it SHALL also link to that section in the reader. No link SHALL open the source PDF.

#### Scenario: Ask about a section
- **WHEN** the user asks a question about the selected risk-factors section
- **THEN** the answer appears incrementally, and on completion the cost, the supplied paragraph ids and a link to the section in the reader are shown

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

### Requirement: Ratios view
The client SHALL show a company's ratios grouped as returned by the API, with one year-over-year line chart per ratio. Fiscal years SHALL run oldest to newest from left to right, even in the right-to-left layout, and values SHALL be formatted by unit (percent, ratio, amount in the reporting currency, or days).

#### Scenario: Malam ratios
- **WHEN** the user opens the ratios view for Malam
- **THEN** each ratio group is shown with a chart per ratio, years increasing from left to right, and gross margin shown as percentages

#### Scenario: Bank company
- **WHEN** the user opens the ratios view for Leumi
- **THEN** the bank ratios and the core ratios are shown, and no margin charts are shown

### Requirement: Gaps for missing years
A chart SHALL show a missing year as a gap in the line, not as zero or as a line drawn through it, and SHALL make the missing reason available for that year.

#### Scenario: Missing year
- **WHEN** Malam's quick ratio has no FY2021 or FY2022 value
- **THEN** its chart has no point for those years, the line does not connect across them, and hovering or focusing the year shows the reason

### Requirement: Low-confidence points
A chart SHALL mark low-confidence values visibly and SHALL show the failed check ids and derived inputs for that value on hover or focus.

#### Scenario: Low-confidence value
- **WHEN** a Malam FY2025 ratio has confidence `low` because the equity check failed
- **THEN** its point is marked as low confidence, and its details name the failed check

### Requirement: Year-over-year change shown
For each ratio the client SHALL show the latest year's value and its change from the previous year, with an indicator for improved, deteriorated, changed or stable.

#### Scenario: Latest value and change
- **WHEN** the ratios view shows Malam's gross margin
- **THEN** the FY2025 value is shown with its change from FY2024 and the status indicator

### Requirement: Ratios point in time
The ratios view SHALL offer the same "available by date" control as the financials view and pass it to the API as `as_of`.

#### Scenario: As-of date
- **WHEN** the user sets an availability date before Malam's FY2025 values were available
- **THEN** the charts have no FY2025 point

### Requirement: OSINT stability view
The client SHALL offer, from the company page, the latest stored OSINT result for a chosen window: overall
label, rationale and Hebrew summary, the six areas with Hebrew names, labels and assessments, risks, strengths,
and numbered sources with link, date, area, signal and confidence. Cited finding numbers SHALL link to their
sources. The view SHALL show run metadata and dropped-finding counts, and state it uses open sources only.

#### Scenario: Stored scorecard
- **WHEN** the user opens the OSINT view of ELAL, which has a stored 36-month result
- **THEN** the scorecard, six areas, risks, strengths, summary and numbered sources are shown, marked as a stored result

#### Scenario: Cited source reachable
- **WHEN** the user follows a finding number cited by a risk
- **THEN** the page moves to that numbered source, which is not hidden under the page header

#### Scenario: Another window
- **WHEN** the user chooses a 12-month window
- **THEN** the view shows the stored 12-month result, or says none has been run for that window

#### Scenario: Never researched
- **WHEN** the user opens the OSINT view of a company with no stored result for the window
- **THEN** an empty state says no research has been run for that window

#### Scenario: Run only in live mode
- **WHEN** the client is in cached mode or the server is cached-only
- **THEN** no action to run research is shown and the view explains why; in live mode the run action is offered

### Requirement: Filing-derived and undated findings marked
In the OSINT view, a finding whose source restates figures from the company's official reports SHALL be
visibly marked as filing-derived, and a finding with no publish date SHALL be visibly marked as undated.

#### Scenario: Marks shown
- **WHEN** the sources include a filing-derived finding and an undated finding
- **THEN** the first carries a filing-derived mark and the second an undated mark, and other findings carry
  neither

### Requirement: Live OSINT run from the client
In live mode the OSINT view SHALL offer to run fresh research for the chosen window, starting only after the
user confirms a warning that a run searches afresh, takes minutes and costs about $1 of OpenRouter credit.
While it runs the view SHALL show progress and keep the previous result; it SHALL then show the new result, or
the error. In cached mode the action SHALL NOT be offered, and the view SHALL say live mode is needed.

#### Scenario: Confirmed live run
- **WHEN** the user in live mode chooses to run research and confirms the cost warning
- **THEN** progress is shown while it runs, and the new result replaces the old one when it is done

#### Scenario: Cancelled before start
- **WHEN** the user dismisses the cost warning
- **THEN** no run is started
