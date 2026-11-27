# Spec Delta

## ADDED Requirements

### Requirement: Company report endpoint
The API SHALL return a company's report at `GET /api/companies/{ticker}/report` in the company report contract (schema version 1.x). In cached mode it SHALL return the report saved for the latest story run, or fail as not cached. In live mode it SHALL build and save that report when it is missing. The response's `mode` SHALL say which happened.

#### Scenario: Cached report exists
- **WHEN** `GET /api/companies/ELAL/report?mode=cached` is called and the report for the latest run is saved
- **THEN** the response is that report with `mode: "cached"`, and no LLM call is made

#### Scenario: Cached report missing
- **WHEN** the same request is made before any report was built for the latest run
- **THEN** the API answers with the not-cached error, which says to request it in live mode

#### Scenario: Live build
- **WHEN** `GET /api/companies/ELAL/report?mode=live` is called and no report is saved for the latest run
- **THEN** the API builds and saves the report and returns it with `mode: "live"`

### Requirement: Axis detail endpoint
The API SHALL return one axis's detail for a fiscal year at `GET /api/companies/{ticker}/report/axes/{axis_id}?year=`, taken from the same saved report. An unknown axis id, or a year without a score, SHALL return the not-found error.

#### Scenario: Detail for an axis
- **WHEN** `GET /api/companies/ELAL/report/axes/growth?year=2025` is called
- **THEN** the response has `axis_id`, `fiscal_year`, `headline`, `factors` and `text`

#### Scenario: Unknown axis
- **WHEN** `axis_id` is `valuation`
- **THEN** the API returns the not-found error

### Requirement: Report from the CLI
The CLI SHALL offer `stock-analyzer report <TICKER> [--live]`, which calls the same server function as the report endpoint and prints the report JSON.

#### Scenario: Same data as the API
- **WHEN** `stock-analyzer report ELAL` runs after the report was built
- **THEN** it prints the same report the cached endpoint returns
