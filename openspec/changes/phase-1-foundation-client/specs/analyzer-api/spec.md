# Spec Delta

## Purpose

Exposes the server's data and analysis functions to clients over HTTP, with a typed, documented contract and streaming, so any client (the web app first) can use exactly what the CLI uses.

## ADDED Requirements

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
- **THEN** each company is returned with ticker, Hebrew name and provider id

### Requirement: Filing endpoints
The API SHALL list a company's annual filings and indicate, for each fiscal year, which filing was selected as the full report and whether its Markdown is cached.

#### Scenario: Selected report flag
- **WHEN** filings for MLTM are requested
- **THEN** filing 32935334 is marked as selected for FY2025

### Requirement: Report endpoints
For a ticker and fiscal year, the API SHALL return the structure tree, the paragraphs of a given node, and the paragraphs of a given page. Each paragraph SHALL include a citation URL that points at its page in the original document.

#### Scenario: Node paragraphs with citations
- **WHEN** the paragraphs of the risk-factors node are requested
- **THEN** each paragraph includes its id, normalized text, page index, printed page and a citation URL ending in `#page=N`

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
The API SHALL accept a question plus a ticker, fiscal year and node or page selection, send only that selected report text and the question to the main LLM role, and stream back the Hebrew answer as server-sent events. A final event SHALL carry token usage, cost and the ids of the paragraphs supplied.

#### Scenario: Streamed answer
- **WHEN** a question about the risk-factors section is submitted
- **THEN** answer increments arrive as events, followed by a final event with cost and the supplied paragraph ids

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
Errors SHALL use one JSON shape with a machine-readable code, a human-readable message and an HTTP status that matches the cause (not found, not cached, upstream failure, validation error, configuration error).

#### Scenario: Unknown ticker
- **WHEN** an unknown ticker is requested
- **THEN** a 404 is returned with code `company_not_found`

### Requirement: Health endpoint
The API SHALL expose an unauthenticated health endpoint that reports liveness and whether provider and LLM credentials are configured, without revealing them.

#### Scenario: Health check
- **WHEN** the health endpoint is called
- **THEN** it returns status ok, plus a true or false flag for each credential
