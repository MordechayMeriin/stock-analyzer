# Spec Delta

## MODIFIED Requirements

### Requirement: Company endpoints
The API SHALL list tracked companies and search provider companies by query.

#### Scenario: Tracked companies
- **WHEN** the client requests tracked companies
- **THEN** each company is returned with ticker, Hebrew name, provider id and its source (`registry` or `added`)

## ADDED Requirements

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
