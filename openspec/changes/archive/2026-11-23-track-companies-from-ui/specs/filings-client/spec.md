# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
