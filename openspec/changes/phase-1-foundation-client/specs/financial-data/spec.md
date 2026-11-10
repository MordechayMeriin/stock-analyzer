# Spec Delta

## Purpose

Normalizes the provider's structured financial line items into exact, typed, point-in-time values per company and fiscal year, as the input for later ratio analysis and the client's financials view.

## ADDED Requirements

### Requirement: Normalized financial values
Each provider line item SHALL become a record with line-item code, statement (income, balance sheet, cash flow or supplemental), fiscal year, value as an exact decimal in base units, currency, the as-reported raw value and scale, the date it became available, and the source filing id.

#### Scenario: Scaled value
- **WHEN** revenue is reported as 4,138,004 with scale "thousands"
- **THEN** the normalized value is exactly 4138004000, and the raw value and scale are preserved

#### Scenario: No floating point
- **WHEN** any financial value is normalized
- **THEN** it is held as an exact decimal and never converted through a binary float

### Requirement: Currency consistency
Within one company, all normalized values SHALL share one currency. A mismatch across years or line items SHALL raise an error naming the conflicting items.

#### Scenario: Mixed currency
- **WHEN** FY2024 values are in ILS and FY2025 values are in USD
- **THEN** normalization fails with an error listing both currencies

### Requirement: Point-in-time availability
Every value SHALL carry an availability timestamp taken from the provider, and the system SHALL be able to return only the values available at or before a given `as_of` date.

#### Scenario: Late availability
- **WHEN** Malam FY2023 values are requested with `as_of` 2024-04-01, and those values became available on 2024-06-13
- **THEN** they are excluded

### Requirement: Financials by year
The system SHALL return a company's normalized values grouped by statement and fiscal year (up to five years), keeping each line item's code and a display label.

#### Scenario: Malam table
- **WHEN** financials for Malam are requested
- **THEN** income, balance-sheet, cash-flow and supplemental items are returned per fiscal year, with revenue FY2025 present
