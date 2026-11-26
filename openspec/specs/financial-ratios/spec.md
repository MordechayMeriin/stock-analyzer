# financial-ratios Specification

## Purpose

Computes deterministic financial ratios from the canonical sheet for every available fiscal year and
returns them as year-over-year series with confidence and reasons, the single source for charts, the API
and LLM tools.

## Requirements

### Requirement: Ratio registry
The system SHALL define each ratio once, with a code, Hebrew name, group, formula over canonical fields, unit (percent, ratio, amount or days), the direction that counts as improvement (or neutral), the change threshold below which a year-over-year change is stable, and the templates it applies to.

#### Scenario: Registry entry
- **WHEN** the registry entry for gross margin is read
- **THEN** it has code, Hebrew name, group profitability, unit percent, direction "higher is better", a change threshold of 0.5 percentage points and template `industrial`

### Requirement: Ratios by template
A company SHALL get exactly the ratios that apply to its template: for `industrial`, gross, operating, EBITDA and net margin, revenue and net income growth, ROE, ROA, current and quick ratio, equity/assets, debt/equity, CFO/net income, free cash flow and FCF margin; for every template, ROE, ROA, equity/assets, net income growth, EPS growth and CFO/net income; for `bank`, also loans/deposits, non-performing loans/loans and loan-loss coverage.

#### Scenario: Insurer ratios
- **WHEN** ratios for Harel (template `insurer`) are requested
- **THEN** the core ratios are returned and no margin ratios are returned

#### Scenario: Bank ratios
- **WHEN** ratios for Leumi (template `bank`) are requested
- **THEN** the core ratios and the bank ratios are returned, including loans/deposits of 73.67% for FY2024

### Requirement: Reported ratios pass through
Ratios the provider reports directly (CET1, Tier 1, total capital and leverage ratios for banks) SHALL be returned as reported, marked `reported`, and never recomputed.

#### Scenario: CET1
- **WHEN** Leumi's ratios are requested
- **THEN** FY2024 CET1 is 11.98% with basis `reported`

### Requirement: Exact ratio values
Ratios SHALL be computed with exact decimal arithmetic and serialized as decimal strings, with percentages expressed as fractions (0.1047 for 10.47%).

#### Scenario: Malam gross margin
- **WHEN** Malam's FY2025 gross margin is computed
- **THEN** it rounds to 0.1047 and is returned as a decimal string, not a JSON float

### Requirement: Average balances
Ratios with a balance-sheet denominator SHALL use the average of the opening and closing balances when both years are available, and the closing balance otherwise, recording which was used.

#### Scenario: ROE with an average
- **WHEN** Malam FY2025 ROE is computed from net income attributable to shareholders and common equity of FY2024 and FY2025
- **THEN** it is about 10.03% and records that an average was used

#### Scenario: Oldest year
- **WHEN** ROE is computed for a company's oldest available year
- **THEN** it uses the closing balance and records that no average was used

### Requirement: Uncomputable ratios
A ratio that cannot be computed for a year SHALL be returned as missing with a reason: an input is missing, the denominator is zero, or the denominator is negative where the ratio is meaningless. A ratio SHALL never be estimated or interpolated.

#### Scenario: Missing input
- **WHEN** Malam's FY2021 quick ratio is requested and FY2021 receivables are missing
- **THEN** the FY2021 value is missing with a reason naming receivables

#### Scenario: No prior year for growth
- **WHEN** revenue growth is requested for the oldest available year
- **THEN** that year's value is missing with the reason "no prior year"

### Requirement: Confidence from checks
Each ratio value SHALL carry confidence `high` or `low`. It SHALL be `low` when any of its inputs took part in a failed data-quality check that year or was derived, and SHALL list the failed check ids and derived inputs.

#### Scenario: Failed equity check
- **WHEN** a Malam FY2025 ratio uses common equity and the FY2025 equity check failed
- **THEN** its confidence is `low` and it lists the equity check

#### Scenario: Derived input
- **WHEN** Malam FY2024 ROE averages FY2023 common equity that was derived
- **THEN** its confidence is `low` and it names the derived input

### Requirement: Year-over-year series
For each ratio the system SHALL return a series with one entry per fiscal year (up to the configured number of years, newest first), each holding the value or missing reason, the confidence, whether an average was used, the input values, and the change from the previous year with a status of improved, deteriorated, changed (neutral ratios), stable or not available.

#### Scenario: Malam series
- **WHEN** ratio series for Malam are requested
- **THEN** gross margin has values for FY2021–FY2025, and FY2025 shows a decrease from FY2024 (10.60% to 10.47%) with status stable, because the change is below the 0.5-point threshold

#### Scenario: Change beyond the threshold
- **WHEN** a higher-is-better ratio falls by more than its threshold from one year to the next
- **THEN** that year's status is deteriorated

### Requirement: Point-in-time ratios
Ratios SHALL be computable as of a date, from a canonical sheet built only from values available at or before it.

#### Scenario: As-of date
- **WHEN** Malam's ratios are requested as of a date before FY2025 values were available
- **THEN** the series has no FY2025 entry

### Requirement: Ratios CLI command
The CLI SHALL print a company's ratio series by group and year from cached data, using the same server function as the API.

#### Scenario: CLI output
- **WHEN** the ratios command is run for MLTM in cached mode
- **THEN** each ratio is printed per fiscal year with low-confidence values marked, and no provider call is made
