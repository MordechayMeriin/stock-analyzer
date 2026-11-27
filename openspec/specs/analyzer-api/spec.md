# analyzer-api Specification

## Purpose

Exposes the server's data and analysis functions to clients over HTTP, with a typed, documented contract and streaming, so any client (the web app first) can use exactly what the CLI uses.

## Requirements

### Requirement: Published API contract
The API SHALL publish a machine-readable OpenAPI description of every endpoint, request and response, and that description SHALL be the single source the client's types are generated from.

#### Scenario: Schema available
- **WHEN** a client requests the OpenAPI document
- **THEN** it describes every endpoint listed in this spec, with typed response bodies

### Requirement: Parity with the CLI
Every API operation SHALL call the same server function the equivalent CLI command uses, so both return the same data for the same inputs.

#### Scenario: Structure parity
- **WHEN** the structure of MLTM FY2025 is requested from the CLI and from the API in cached mode
- **THEN** both return the same node ids, titles and page ranges

### Requirement: Company endpoints
The API SHALL list tracked companies and search provider companies by query.

#### Scenario: Tracked companies
- **WHEN** the client requests tracked companies
- **THEN** each company is returned with ticker, Hebrew name, provider id and its source (`registry` or `added`)

### Requirement: Add tracked company endpoint
The API SHALL add a tracked company from a provider id, ticker, Hebrew name and optional English name and ISIN, and SHALL return the added company. The request SHALL run in live mode. It SHALL be refused in cached mode and on a cached-only server.

#### Scenario: Added in live mode
- **WHEN** a live-mode request adds provider company 1234 as ABC
- **THEN** the response is 201 with the company and source `added`, and the next tracked-companies request includes ABC

#### Scenario: Cached mode
- **WHEN** a cached-mode request tries to add a company
- **THEN** it is refused with a 403 and code `live_required`, and nothing is added

#### Scenario: Cached-only server
- **WHEN** a live-mode add request reaches a server configured cached-only
- **THEN** it is refused with code `live_disabled`, and nothing is added

#### Scenario: Already tracked
- **WHEN** a live-mode request adds a ticker or provider id that is already tracked
- **THEN** it is refused with a 409 and code `company_already_tracked`

### Requirement: Remove tracked company endpoint
The API SHALL stop tracking a company that was added at runtime, by ticker. The request SHALL run in live mode, with the same refusals as adding.

#### Scenario: Removed in live mode
- **WHEN** a live-mode request removes the added company ABC
- **THEN** the response is 204, and ABC is no longer listed or resolvable

#### Scenario: Version-controlled company
- **WHEN** a live-mode request removes MLTM
- **THEN** it is refused with a 409 and code `company_not_removable`

#### Scenario: Unknown ticker
- **WHEN** a live-mode request removes an untracked ticker
- **THEN** it is refused with a 404 and code `company_not_found`

### Requirement: Filing endpoints
The API SHALL list a company's annual filings and indicate, for each fiscal year, which filing was selected as the full report, whether its Markdown is cached, and its Markdown availability at the provider (`available`, `unknown`, `processing` or `failed`; absent when nothing is selected). Each filing entry SHALL carry the provider's processing status. Filing entries SHALL NOT carry document or viewer URLs.

#### Scenario: Selected report flag
- **WHEN** filings for MLTM are requested
- **THEN** filing 32935334 is marked as selected for FY2025

#### Scenario: No document links
- **WHEN** filings for any company are requested
- **THEN** no filing entry has a document URL or viewer URL field

#### Scenario: Year waiting for the provider
- **WHEN** filings for RMLI are requested and FY2024's selected filing 61337033 has status `QUEUED`
- **THEN** FY2024 shows 61337033 as selected with Markdown availability `processing`, and FY2025 shows `available`

#### Scenario: Availability mapping
- **WHEN** a year's selected filing has status `COMPLETED`, no status, `PENDING`/`QUEUED`/`PROCESSING`, or `FAILED`/`SKIPPED`
- **THEN** the year's Markdown availability is `available`, `unknown`, `processing` or `failed` respectively; any other status is `unknown`

#### Scenario: No selection
- **WHEN** a year has no candidate full report
- **THEN** its selection error is set and it has no Markdown availability

### Requirement: Report endpoints
For a ticker and fiscal year, the API SHALL return the structure tree, the paragraphs of a given node, and the paragraphs of a given page, where a page is a page of the report's Markdown. Each paragraph SHALL include its id, normalized text, page index and printed page (when known). No response SHALL include a link to the source PDF.

#### Scenario: Node paragraphs with citations
- **WHEN** the paragraphs of the risk-factors node are requested
- **THEN** each paragraph includes its id, normalized text, page index and printed page, and no citation URL

#### Scenario: Structure without a document link
- **WHEN** the structure tree of a report is requested
- **THEN** the response has no document URL field

### Requirement: Financials endpoint
The API SHALL return a company's normalized financial values grouped by statement and fiscal year, with each value serialized as an exact decimal string.

#### Scenario: Decimal serialization
- **WHEN** financials are returned
- **THEN** each monetary value is a decimal string, never a JSON float

### Requirement: Usage endpoint
The API SHALL return the current provider credit usage and the LLM spend totals from the logs.

#### Scenario: Usage panel data
- **WHEN** usage is requested
- **THEN** provider credits used and remaining, and total LLM cost, are returned

### Requirement: Streaming playground
The API SHALL accept a question plus a ticker, fiscal year and node or page selection, send only that selected report text and the question to the main LLM role, and stream back the Hebrew answer as server-sent events. A final event SHALL carry token usage, cost and the ids of the paragraphs supplied, and no links to the source document.

#### Scenario: Streamed answer
- **WHEN** a question about the risk-factors section is submitted
- **THEN** answer increments arrive as events, followed by a final event with cost and the supplied paragraph ids, and without a citation map

#### Scenario: Oversized selection
- **WHEN** the selected text exceeds the configured context budget
- **THEN** the request is rejected with a clear error asking for a narrower selection

### Requirement: Cached and live modes
Each request SHALL run in cached mode (local data only, no provider calls) or live mode. The server SHALL be configurable to allow cached mode only, and in that case live requests SHALL be refused.

#### Scenario: Cached miss
- **WHEN** a cached-mode request needs data that is not cached
- **THEN** the API answers with a "not cached" error, and no provider call is made

#### Scenario: Live disabled
- **WHEN** a live-mode request reaches a server configured cached-only
- **THEN** it is refused with an explanatory error

### Requirement: Consistent error responses
Errors SHALL use one JSON shape with a machine-readable code, a human-readable message and an HTTP status that matches the cause (not found, not cached, report not yet processed by the provider, upstream failure, validation error, configuration error).

#### Scenario: Unknown ticker
- **WHEN** an unknown ticker is requested
- **THEN** a 404 is returned with code `company_not_found`

#### Scenario: Report not processed by the provider
- **WHEN** a live-mode request for the RMLI FY2024 report structure needs Markdown the provider has not produced
- **THEN** a 409 is returned with code `report_not_processed` and a message naming the filing and its provider status

### Requirement: Health endpoint
The API SHALL expose an unauthenticated health endpoint that reports liveness, whether provider and LLM credentials are configured, and which state store backend is active and whether it is reachable, without revealing credentials or connection details.

#### Scenario: Health check
- **WHEN** the health endpoint is called
- **THEN** it returns status ok, plus a true or false flag for each credential

#### Scenario: Storage reported
- **WHEN** the health endpoint is called on a server using a database
- **THEN** it names the database backend and reports it as reachable, without the database URL or any part of it

#### Scenario: Storage unreachable
- **WHEN** the health endpoint is called while the database cannot be reached
- **THEN** it still answers, and it reports storage as unreachable

### Requirement: Ratios endpoint
The API SHALL return a company's ratio series, grouped, for an optional `as_of` date, with the company's template, currency and fiscal years. Every ratio value and input SHALL be serialized as an exact decimal string. The endpoint SHALL call the same server function as the ratios CLI command.

#### Scenario: Malam ratios
- **WHEN** the ratios of MLTM are requested in cached mode
- **THEN** the response carries template `industrial`, the fiscal years, and ratio series grouped by group, each value a decimal string or missing with a reason

#### Scenario: Low-confidence value
- **WHEN** a ratio value in the response depends on a failed data-quality check
- **THEN** that value has confidence `low` and lists the failed check ids

#### Scenario: Financials not cached
- **WHEN** a cached-mode request asks for ratios of a company whose financials are not cached
- **THEN** the API answers with the "not cached" error, and no provider call is made

#### Scenario: Unsupported template
- **WHEN** ratios are requested for a company whose template has no canonical fields
- **THEN** a 422 is returned with code `template_not_supported`, naming the template

### Requirement: OSINT endpoints
The API SHALL expose OSINT research at `/api/companies/{ticker}/osint` with an optional window of 1 to 120
months (default the configured one). `GET` SHALL return the latest stored result and never search or call an
LLM, in any mode. `POST` SHALL run the research afresh in live mode through the research CLI's server function,
store it, and stream `progress` events, then one `done` event with the result or one `error` event. Refusals
SHALL come as plain JSON errors before the stream.

#### Scenario: Stored result
- **WHEN** ELAL has been researched with a 36-month window and the client requests its OSINT result in either mode
- **THEN** the stored scorecard, findings and run statistics are returned, marked as stored, and no search or LLM call is made

#### Scenario: Never researched
- **WHEN** the OSINT result of a tracked company that was never researched for the window is requested
- **THEN** a 409 is returned with code `not_cached`

#### Scenario: Untracked ticker
- **WHEN** the OSINT result of a ticker that is not tracked is requested, or a run for it
- **THEN** a 404 is returned with code `company_not_found`, and no search or LLM call is made

#### Scenario: Run refused outside live mode
- **WHEN** a research run is requested in cached mode, or on a server with live calls disabled
- **THEN** a 403 is returned with code `live_required` or `live_disabled` before any stream starts, and no search or LLM call is made

#### Scenario: Run in live mode
- **WHEN** a research run for ELAL is requested in live mode
- **THEN** the stream carries progress events (step, area, searches used, search limit) with searches used never
  above the limit, then one `done` event with the new result, which replaces the stored one for that window

#### Scenario: Run already in progress
- **WHEN** a research run is requested for a ticker and window while another run for them is still running
- **THEN** a 409 is returned with code `research_in_progress`, and the first run is not affected

#### Scenario: Client disconnects during a run
- **WHEN** the client closes the stream before the run finishes
- **THEN** the run continues and its result is stored

#### Scenario: No verified findings
- **WHEN** a run ends without any finding that survives verification
- **THEN** the stream ends with an `error` event with code `osint_no_findings`, and the previously stored result is kept

#### Scenario: Missing OpenRouter key
- **WHEN** a live run is requested and the OpenRouter key is not configured
- **THEN** a 503 is returned with code `missing_credential` before any stream starts

#### Scenario: Window out of range
- **WHEN** a result or a run is requested with a window below 1 or above 120 months
- **THEN** a 422 is returned with code `validation_error`

### Requirement: Saved story endpoint
The API SHALL return a company's latest saved story run, with its sections, findings, rendered fact values, fact registry, citations with page URLs, web sources with their URL, title, publish date and excerpt, the fiscal years covered, `as_of`, models and cost. Fact values SHALL be serialized as exact decimal strings. This endpoint SHALL make no LLM or provider call.

#### Scenario: Saved story
- **WHEN** the story for MLTM is requested after a successful run
- **THEN** the saved run is returned, each fact value is a decimal string, and each citation has a URL ending in `#page=N`

#### Scenario: No story yet
- **WHEN** the story is requested for a company with no saved run
- **THEN** the API answers with the "not cached" error

#### Scenario: Web sources returned
- **WHEN** the saved story cites a web source
- **THEN** the response lists that source with its URL, title, publish date and excerpt, and each paragraph lists the source ids it cites

### Requirement: Streamed story run
In live mode, the API SHALL accept a story request for a ticker with an optional `as_of`, run it, and stream its progress as server-sent events. The final event SHALL carry either the saved story run or an error. Validation, the token budget, mode checks and a conflicting OSINT research run SHALL be checked before the stream starts and SHALL be returned as ordinary error responses.

#### Scenario: Live run
- **WHEN** a live story run is requested for MLTM
- **THEN** progress events arrive in order, and the final event carries the saved story run

#### Scenario: Cached mode refused
- **WHEN** a story run is requested in cached mode
- **THEN** the request is refused with an error explaining that a story run needs live mode, and no LLM call is made

#### Scenario: Over budget
- **WHEN** the estimated input of a story run exceeds the configured budget
- **THEN** the request is rejected before the stream starts, with the estimate and the budget in the error

#### Scenario: Research in progress
- **WHEN** a story run needs an OSINT research run and one for the same company is already running
- **THEN** the request is rejected before the stream starts with the "research in progress" error

### Requirement: Report comparison and ratio endpoints
The API SHALL return the business-section comparison for a ticker and fiscal years, and the core ratios with their changes, confidence and check results for a ticker, calling the same functions as the CLI.

#### Scenario: Ratio parity
- **WHEN** the core ratios of MLTM are requested from the CLI and from the API in cached mode
- **THEN** both return the same values, confidence and failed checks
