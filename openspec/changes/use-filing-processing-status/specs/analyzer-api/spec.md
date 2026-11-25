# Spec Delta

## MODIFIED Requirements

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

### Requirement: Consistent error responses
Errors SHALL use one JSON shape with a machine-readable code, a human-readable message and an HTTP status that matches the cause (not found, not cached, report not yet processed by the provider, upstream failure, validation error, configuration error).

#### Scenario: Unknown ticker
- **WHEN** an unknown ticker is requested
- **THEN** a 404 is returned with code `company_not_found`

#### Scenario: Report not processed by the provider
- **WHEN** a live-mode request for the RMLI FY2024 report structure needs Markdown the provider has not produced
- **THEN** a 409 is returned with code `report_not_processed` and a message naming the filing and its provider status
