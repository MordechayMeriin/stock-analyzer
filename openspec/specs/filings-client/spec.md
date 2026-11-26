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
The system SHALL list a company's annual-report filings newest first, including each filing's id, title, fiscal year, release time, file extension, file size, document URL and the provider's Markdown processing status (absent when the provider gives none).

#### Scenario: Several filings per year
- **WHEN** the filings for Malam are listed
- **THEN** every 10-K filing for FY2024 and FY2025 is returned, including cover forms and iXBRL wrappers

#### Scenario: Processing status carried
- **WHEN** the filings for Rami Levy are listed
- **THEN** filing 61337033 (FY2024) carries the status `QUEUED` and filing 33051170 (FY2025) carries `COMPLETED`

### Requirement: Annual report selection
For each fiscal year the system SHALL choose exactly one full report: the fiscal year comes from the filing's fiscal-year field or the first `20\d\d` in its title; candidates must be PDF filings without "iXBRL" in the title whose title names a periodic report; the largest file wins. If no candidate exists, selection SHALL fail with an error naming the company and year.

#### Scenario: Malam FY2025
- **WHEN** the FY2025 report for Malam is selected
- **THEN** filing 32935334 is chosen, not the cover form 32935333

#### Scenario: Malam FY2024 with iXBRL wrapper
- **WHEN** the FY2024 report for Malam is selected
- **THEN** filing 63741657 is chosen, not 63728804 or the iXBRL wrapper 63741654

#### Scenario: No candidate
- **WHEN** a year has only HTM and iXBRL filings
- **THEN** selection fails with an error that names the ticker and fiscal year

#### Scenario: Trustee report is not an annual report
- **WHEN** Delek Group's only PDF filing for FY2026 is titled `דו"ח שנתי – נאמנות למחזיקי אגרות החוב (סדרה לז'), הרמטיק`
- **THEN** no report is selected for FY2026, and the error lists that filing

#### Scenario: English and Hebrew titles
- **WHEN** a year's PDF is titled `Periodic and annual report for 2025` or `דוח תקופתי ושנתי לשנת 2024`
- **THEN** it is a candidate: a title names a periodic report when it contains `תקופתי`, or `periodic` in any letter case

### Requirement: Complete report Markdown retrieval
The system SHALL retrieve a filing's full Markdown text using as few paged calls as possible, and SHALL verify that the assembled length equals the provider's reported total character count. The text and its metadata SHALL be saved per ticker and fiscal year. When the provider has no Markdown for a filing that is not `COMPLETED`, retrieval SHALL fail with a "report not processed" error naming the company, year, filing and provider status.

#### Scenario: Multi-page fetch
- **WHEN** a report longer than one page of results is fetched
- **THEN** pages are requested by following the provider's next-offset until done, and the assembled text length equals the reported total

#### Scenario: Truncated content
- **WHEN** the assembled length differs from the reported total
- **THEN** the fetch fails and nothing is saved as complete

#### Scenario: Provider has not processed the report
- **WHEN** the Rami Levy FY2024 report is fetched live and its selected filing 61337033 still has status `QUEUED` after any filing list refresh
- **THEN** the fetch fails with a "report not processed" error naming RMLI, FY2024, filing 61337033 and `QUEUED`, no Markdown request is made, and nothing is saved

#### Scenario: Unknown status turns out unprocessed
- **WHEN** a filing with no processing status is fetched and the provider answers 404 for its Markdown
- **THEN** the fetch fails with a "report not processed" error, and nothing is saved

#### Scenario: Missing Markdown for a completed filing
- **WHEN** the provider answers 404 for the Markdown of a filing whose status is `COMPLETED`
- **THEN** the fetch fails with the provider not-found error, as for any other missing resource

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
The system SHALL keep a version-controlled list of tracked companies with ticker, Hebrew name, provider company id and ISIN. It SHALL also keep companies added at runtime in the state store. The tracked companies SHALL be the version-controlled list followed by the added companies, each marked with its source (`registry` or `added`). The system SHALL resolve a ticker through both, case-insensitively.

#### Scenario: Resolve ticker
- **WHEN** ticker MLTM is resolved
- **THEN** provider company id 6901 and Hebrew name "מלם תים" are returned

#### Scenario: Resolve an added company
- **GIVEN** a company with ticker ABC was added at runtime
- **WHEN** ticker "abc" is resolved
- **THEN** that company is returned with source `added`, and its filings, reports and financials can be requested like those of any tracked company

#### Scenario: Version-controlled list wins
- **GIVEN** an added company whose ticker or provider id was later also put in the version-controlled list
- **WHEN** the tracked companies are listed
- **THEN** only the version-controlled entry appears, with source `registry`

### Requirement: Add a tracked company
The system SHALL add a company to the tracked companies from a provider company id, a ticker and a Hebrew name, with optional English name and ISIN. The ticker SHALL be stored in upper case. Adding SHALL be refused when the ticker or the provider id is already tracked from either source, or when the ticker is not 1–15 characters of Latin letters, digits, dots or hyphens.

#### Scenario: Add a new company
- **WHEN** provider company 1234 is added with ticker "abc" and Hebrew name "חברה לדוגמה"
- **THEN** the tracked companies include ABC with source `added`, and it is still tracked after the server restarts

#### Scenario: Duplicate ticker
- **WHEN** a company is added with ticker MLTM
- **THEN** it is refused with an "already tracked" error and the tracked companies are unchanged

#### Scenario: Duplicate provider id
- **WHEN** provider company 6901 is added under a different ticker
- **THEN** it is refused with an "already tracked" error naming MLTM

#### Scenario: Invalid ticker
- **WHEN** a company is added with ticker "A B/C"
- **THEN** it is refused with a validation error

### Requirement: Remove an added company
The system SHALL stop tracking a company that was added at runtime. It SHALL refuse to remove a company from the version-controlled list. Removing SHALL keep the company's cached reports, financials and usage records.

#### Scenario: Remove an added company
- **GIVEN** ABC was added at runtime and its FY2025 report was fetched
- **WHEN** ABC is removed
- **THEN** ABC is no longer tracked, and adding it again serves the FY2025 report from the cache with no provider call

#### Scenario: Version-controlled company
- **WHEN** removal of MLTM is requested
- **THEN** it is refused with a "not removable" error and MLTM stays tracked

#### Scenario: Unknown ticker
- **WHEN** removal of an untracked ticker is requested
- **THEN** it is refused with a "company not found" error

### Requirement: API credentials from environment
The provider API key SHALL be read only from the environment and SHALL never be written to logs, cache files or API responses.

#### Scenario: Missing key in live mode
- **WHEN** a network call is needed and no API key is configured
- **THEN** the call fails with an error explaining which variable to set

### Requirement: Selection prefers processed filings
Among a fiscal year's full-report candidates, the system SHALL prefer one whose Markdown is available or of unknown status over one the provider has not processed or could not convert, and SHALL apply the largest-file rule only among candidates of the same availability. A year whose candidates are all unprocessed SHALL still select one.

#### Scenario: Processed report wins over a larger unprocessed one
- **WHEN** a year has two periodic-report PDFs, a larger one with status `QUEUED` and a smaller one with status `COMPLETED`
- **THEN** the `COMPLETED` filing is selected

#### Scenario: Unknown status counts as available
- **WHEN** a year has two periodic-report PDFs, a larger one with no status and a smaller one with status `COMPLETED`
- **THEN** the larger filing is selected

#### Scenario: Only unprocessed candidates
- **WHEN** Delek Group's FY2023 periodic-report PDFs 61330467 and 61325682 both have status `QUEUED`
- **THEN** the larger, 61330467, is still selected, and its Markdown availability is reported as processing

### Requirement: Filing list refresh for unprocessed reports
In live mode, when the report needed for a year (or, when listing a company's filings, any year's selected report) is not marked available and the company's cached filing list is more than one day old, the system SHALL request the filing list from the provider again, replacing the cached copy, before selecting. It SHALL do so at most once per company per request.

#### Scenario: Provider finished processing since the list was cached
- **WHEN** a live fetch needs Rami Levy FY2024, the filing list cached three days ago shows 61337033 as `QUEUED`, and the provider now reports it `COMPLETED`
- **THEN** the filing list is requested again, 61337033 is selected as available, and its Markdown is fetched and saved

#### Scenario: Live filings listing
- **WHEN** Rami Levy's filings are listed in live mode and the cached list is two days old with FY2024's selected filing `QUEUED`
- **THEN** the filing list is requested again once, and the listing reflects the provider's current statuses

#### Scenario: Recently cached list
- **WHEN** a live fetch needs a year whose selected filing is `QUEUED` and the company's filing list was cached less than a day ago
- **THEN** the filing list is not requested again

#### Scenario: Cached mode
- **WHEN** a cached-mode request needs a year whose selected filing is `QUEUED`
- **THEN** no provider call is made
