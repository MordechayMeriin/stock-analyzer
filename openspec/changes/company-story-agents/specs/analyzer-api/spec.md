# Spec Delta

## ADDED Requirements

### Requirement: Saved story endpoint
The API SHALL return a company's latest saved story run, with its sections, findings, rendered fact values, fact registry, citations with page URLs, the fiscal years covered, `as_of`, models and cost. Fact values SHALL be serialized as exact decimal strings. This endpoint SHALL make no LLM or provider call.

#### Scenario: Saved story
- **WHEN** the story for MLTM is requested after a successful run
- **THEN** the saved run is returned, each fact value is a decimal string, and each citation has a URL ending in `#page=N`

#### Scenario: No story yet
- **WHEN** the story is requested for a company with no saved run
- **THEN** the API answers with the "not cached" error

### Requirement: Streamed story run
In live mode, the API SHALL accept a story request for a ticker with an optional `as_of`, run it, and stream its progress as server-sent events. The final event SHALL carry either the saved story run or an error. Validation, the token budget and mode checks SHALL be applied before the stream starts and SHALL be returned as ordinary error responses.

#### Scenario: Live run
- **WHEN** a live story run is requested for MLTM
- **THEN** progress events arrive in order, and the final event carries the saved story run

#### Scenario: Cached mode refused
- **WHEN** a story run is requested in cached mode
- **THEN** the request is refused with an error explaining that a story run needs live mode, and no LLM call is made

#### Scenario: Over budget
- **WHEN** the estimated input of a story run exceeds the configured budget
- **THEN** the request is rejected before the stream starts, with the estimate and the budget in the error

### Requirement: Report comparison and ratio endpoints
The API SHALL return the business-section comparison for a ticker and fiscal years, and the core ratios with their changes, confidence and check results for a ticker, calling the same functions as the CLI.

#### Scenario: Ratio parity
- **WHEN** the core ratios of MLTM are requested from the CLI and from the API in cached mode
- **THEN** both return the same values, confidence and failed checks
