# Spec Delta

## MODIFIED Requirements

### Requirement: Annual report filings listing
The system SHALL list a company's annual-report filings newest first, including each filing's id, title, fiscal year, release time, file extension, file size, document URL and the provider's Markdown processing status (absent when the provider gives none).

#### Scenario: Several filings per year
- **WHEN** the filings for Malam are listed
- **THEN** every 10-K filing for FY2024 and FY2025 is returned, including cover forms and iXBRL wrappers

#### Scenario: Processing status carried
- **WHEN** the filings for Rami Levy are listed
- **THEN** filing 61337033 (FY2024) carries the status `QUEUED` and filing 33051170 (FY2025) carries `COMPLETED`

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

## ADDED Requirements

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
