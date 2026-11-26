# Spec Delta

## ADDED Requirements

### Requirement: Ratios view
The client SHALL show a company's ratios grouped as returned by the API, with one year-over-year line chart per ratio. Fiscal years SHALL run oldest to newest from left to right, even in the right-to-left layout, and values SHALL be formatted by unit (percent, ratio, amount in the reporting currency, or days).

#### Scenario: Malam ratios
- **WHEN** the user opens the ratios view for Malam
- **THEN** each ratio group is shown with a chart per ratio, years increasing from left to right, and gross margin shown as percentages

#### Scenario: Bank company
- **WHEN** the user opens the ratios view for Leumi
- **THEN** the bank ratios and the core ratios are shown, and no margin charts are shown

### Requirement: Gaps for missing years
A chart SHALL show a missing year as a gap in the line, not as zero or as a line drawn through it, and SHALL make the missing reason available for that year.

#### Scenario: Missing year
- **WHEN** Malam's quick ratio has no FY2021 or FY2022 value
- **THEN** its chart has no point for those years, the line does not connect across them, and hovering or focusing the year shows the reason

### Requirement: Low-confidence points
A chart SHALL mark low-confidence values visibly and SHALL show the failed check ids and derived inputs for that value on hover or focus.

#### Scenario: Low-confidence value
- **WHEN** a Malam FY2025 ratio has confidence `low` because the equity check failed
- **THEN** its point is marked as low confidence, and its details name the failed check

### Requirement: Year-over-year change shown
For each ratio the client SHALL show the latest year's value and its change from the previous year, with an indicator for improved, deteriorated, changed or stable.

#### Scenario: Latest value and change
- **WHEN** the ratios view shows Malam's gross margin
- **THEN** the FY2025 value is shown with its change from FY2024 and the status indicator

### Requirement: Ratios point in time
The ratios view SHALL offer the same "available by date" control as the financials view and pass it to the API as `as_of`.

#### Scenario: As-of date
- **WHEN** the user sets an availability date before Malam's FY2025 values were available
- **THEN** the charts have no FY2025 point
