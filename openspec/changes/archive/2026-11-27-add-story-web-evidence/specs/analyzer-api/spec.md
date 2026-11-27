# Spec Delta

## MODIFIED Requirements

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
