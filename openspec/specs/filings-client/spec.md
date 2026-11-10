# filings-client Specification

## Purpose

Retrieves Israeli listed companies, their periodic-report filings, report text as Markdown and structured financials from the FinancialFilings REST API, reliably, cheaply and reproducibly.

## Requirements

### Requirement: Company search
The system SHALL search companies by name or ticker, restricted to Israel, and return each match's provider company id, name, ticker and ISIN when available.

#### Scenario: Search by Hebrew name
- **WHEN** a search for "מלם" is requested
- **THEN** the results include Malam Team with its provider company id and ISIN

#### Scenario: No match
- **WHEN** a search matches no Israeli company
- **THEN** an empty list is returned, not an error

### Requirement: Annual report filings listing
The system SHALL list a company's annual-report filings newest first, including each filing's id, title, fiscal year, release time, file extension, file size and document URL.

#### Scenario: Several filings per year
- **WHEN** the filings for Malam are listed
- **THEN** every 10-K filing for FY2024 and FY2025 is returned, including cover forms and iXBRL wrappers

### Requirement: Annual report selection
For each fiscal year the system SHALL choose exactly one full report: the fiscal year comes from the filing's fiscal-year field or the first `20\d\d` in its title; candidates must be PDF filings without "iXBRL" in the title; the largest file wins. If no candidate exists, selection SHALL fail with an error naming the company and year.

#### Scenario: Malam FY2025
- **WHEN** the FY2025 report for Malam is selected
- **THEN** filing 32935334 is chosen, not the cover form 32935333

#### Scenario: Malam FY2024 with iXBRL wrapper
- **WHEN** the FY2024 report for Malam is selected
- **THEN** filing 63741657 is chosen, not 63728804 or the iXBRL wrapper 63741654

#### Scenario: No candidate
- **WHEN** a year has only HTM and iXBRL filings
- **THEN** selection fails with an error that names the ticker and fiscal year

### Requirement: Complete report Markdown retrieval
The system SHALL retrieve a filing's full Markdown text using as few paged calls as possible, and SHALL verify that the assembled length equals the provider's reported total character count. The text and its metadata SHALL be saved per ticker and fiscal year.

#### Scenario: Multi-page fetch
- **WHEN** a report longer than one page of results is fetched
- **THEN** pages are requested by following the provider's next-offset until done, and the assembled text length equals the reported total

#### Scenario: Truncated content
- **WHEN** the assembled length differs from the reported total
- **THEN** the fetch fails and nothing is saved as complete

### Requirement: Financials retrieval
The system SHALL retrieve a company's annual structured financial line items for all available years, and a second set that includes revisions where the provider supports it.

#### Scenario: Fetch Malam financials
- **WHEN** financials for Malam are fetched
- **THEN** line items for every available fiscal year are returned with their values, scale and currency

### Requirement: Permanent response cache
Every successful provider response SHALL be cached on disk, keyed by request path and parameters, and reused on later identical requests without contacting the provider. A refresh option SHALL bypass and overwrite the cache.

#### Scenario: Repeat request
- **WHEN** the same request is made twice
- **THEN** the second request is served from the cache and uses no credits

#### Scenario: Forced refresh
- **WHEN** a request is made with refresh enabled
- **THEN** the provider is called and the cached entry is replaced

#### Scenario: Offline mode
- **WHEN** the system runs in cached-only mode and a request is not cached
- **THEN** it fails with a "not cached" error and makes no network call

### Requirement: Resilient provider calls
The system SHALL retry rate-limited (429) and server-error (5xx) responses with exponential backoff, honoring a `Retry-After` header when present, up to a configured maximum number of attempts. Client errors other than 429 SHALL fail immediately.

#### Scenario: Rate limited
- **WHEN** the provider answers 429 with `Retry-After: 2`
- **THEN** the system waits at least 2 seconds and retries

#### Scenario: Not found
- **WHEN** the provider answers 404
- **THEN** the call fails at once with an error naming the resource

### Requirement: Credit accounting
The system SHALL append one log record per provider call (time, endpoint, parameters, status, cache hit or miss, estimated credits) and SHALL report the account's current credit usage on request.

#### Scenario: Logged call
- **WHEN** a Markdown page is fetched from the network
- **THEN** a log record with its estimated credit cost is appended

#### Scenario: Usage query
- **WHEN** usage is requested
- **THEN** the provider's current usage figures are returned without consuming credits

### Requirement: Tracked company registry
The system SHALL keep a version-controlled list of tracked companies with ticker, Hebrew name, provider company id and ISIN, and SHALL resolve a ticker through it.

#### Scenario: Resolve ticker
- **WHEN** ticker MLTM is resolved
- **THEN** provider company id 6901 and Hebrew name "מלם תים" are returned

### Requirement: API credentials from environment
The provider API key SHALL be read only from the environment and SHALL never be written to logs, cache files or API responses.

#### Scenario: Missing key in live mode
- **WHEN** a network call is needed and no API key is configured
- **THEN** the call fails with an error explaining which variable to set
