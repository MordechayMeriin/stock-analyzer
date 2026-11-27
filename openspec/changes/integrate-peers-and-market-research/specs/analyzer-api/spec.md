# Analyzer API delta

## ADDED Requirements

### Requirement: Peer financials over HTTP

`GET /api/companies/{ticker}/peer-financials` SHALL return the peer service result using a positive limit and optional foreign country codes. It SHALL default to cached mode. The API SHALL preserve selection context, issuer identity, reporting currencies, fiscal years, and decimal strings.

#### Scenario: Cached peers for a ticker

- **WHEN** cached peer financials are requested for a tracked ticker
- **THEN** the response matches the peer CLI result for the same scope without provider calls

#### Scenario: No domestic matches

- **WHEN** the peer service reports zero domestic matches and the request names no foreign markets
- **THEN** the API returns a successful empty peer list and the selection reason

### Requirement: Industry market research over HTTP

`GET /api/companies/{ticker}/market-research` SHALL return the latest stored brief for the requested market set and window. `POST` to the same path SHALL start fresh research only in live mode and return the resulting brief. Both methods SHALL use the market research service and its default markets.

#### Scenario: Cached read in the live interface

- **WHEN** an analyst opens an existing brief while the client is in live mode
- **THEN** GET serves the stored result without contacting FinancialFilings or the web research provider

#### Scenario: Fresh run requested on a cached-only server

- **WHEN** a fresh market research run is requested with live access disabled
- **THEN** the API refuses the request without contacting a provider
