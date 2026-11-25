# Spec Delta

## MODIFIED Requirements

### Requirement: Company and filing browser
The client SHALL let the user pick a tracked company or search for one, show its annual filings by fiscal year with the selected full report marked and its cached status, and show provider credit usage. Filings SHALL be shown without links to their documents. A year whose selected report is not cached and whose Markdown the provider has not processed or could not convert SHALL be shown as unavailable, with the reason, and without actions to read the report or ask about it.

#### Scenario: Pick Malam
- **WHEN** the user selects Malam
- **THEN** FY2024 and FY2025 are listed, each with its selected report and cached status, and the credit usage is visible

#### Scenario: No document links
- **WHEN** the filings of any company are shown
- **THEN** no filing has a link that opens its PDF

#### Scenario: Report waiting for the provider
- **WHEN** the user opens Rami Levy and FY2024's selected report is not cached and has Markdown availability `processing`
- **THEN** FY2024 is marked as not yet processed by the provider, explains that its text is not available yet, and offers no action to read it or ask about it

#### Scenario: Report the provider could not convert
- **WHEN** a year's selected report is not cached and has Markdown availability `failed`
- **THEN** the year is marked as one the provider could not convert, and offers no action to read it or ask about it

#### Scenario: Cached report stays readable
- **WHEN** a year's selected report is cached, whatever its Markdown availability
- **THEN** the actions to read it and ask about it are offered

#### Scenario: Unknown availability
- **WHEN** a year's selected report is not cached and has Markdown availability `unknown` or `available`
- **THEN** the actions to read it and ask about it are offered, as today
