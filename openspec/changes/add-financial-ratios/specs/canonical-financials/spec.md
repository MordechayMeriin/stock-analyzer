# Spec Delta

## Purpose

Standardizes a company's normalized financial values into a fixed, template-specific set of canonical
fields per fiscal year, with the provenance of every value and accounting-identity checks, so ratios and
charts are computed from consistent inputs.

## ADDED Requirements

### Requirement: Template-specific canonical fields
The system SHALL build, for each company and fiscal year, a canonical sheet whose fields are fixed by the company's template (`industrial`, `bank` or `insurer`). Every field of the template SHALL be present in every year's sheet, holding a value or marked missing.

#### Scenario: Industrial sheet
- **WHEN** the canonical sheet for Malam (template `industrial`) is built
- **THEN** each fiscal year has the same industrial fields, including revenue, gross profit, total assets, total equity, common equity and cash from operations

#### Scenario: Bank sheet
- **WHEN** the canonical sheet for Leumi (template `bank`) is built
- **THEN** each fiscal year has the bank fields, including loans to customers, customer deposits and the reported capital ratios, and no industrial-only fields such as gross profit

#### Scenario: Unknown template
- **WHEN** a company's financials carry a template the system has no canonical fields for
- **THEN** building the sheet fails with an error naming the template, and no ratios are computed for it

### Requirement: Ordered value resolution
Each canonical field SHALL be resolved from an ordered list of sources: its reported line-item code, then fallback codes, then derivation rules over other canonical fields. The first source that yields a value SHALL be used; later sources SHALL NOT override it.

#### Scenario: Reported value wins
- **WHEN** Malam FY2025 reports common equity of 767,184,000
- **THEN** the canonical common equity is 767184000 with basis `reported`, even though total equity and minority interest are also reported

#### Scenario: Derived when the total is missing
- **WHEN** Malam FY2023 reports total equity 613,453,000 and minority interest −4,388,000 but no common equity
- **THEN** canonical common equity is derived as total equity − minority interest = 617841000, with basis `derived` and the rule id

#### Scenario: Nothing to resolve from
- **WHEN** Malam FY2021 has neither receivables nor any source a receivables rule needs
- **THEN** canonical receivables for FY2021 is marked missing

### Requirement: Cell provenance
Every canonical cell SHALL carry its basis (`reported`, `derived` or `missing`), the line-item code or derivation rule id it came from, the cells it was derived from, its source filing id and its availability timestamp. A derived cell's availability SHALL be the latest availability among its inputs.

#### Scenario: Provenance of a derived cell
- **WHEN** Malam FY2023 common equity is derived
- **THEN** its provenance names the rule and the total-equity and minority-interest cells it used, and its availability is the later of their two timestamps

### Requirement: Exact values
Canonical values SHALL be exact decimals in base units, and derivation SHALL never pass through binary floating point.

#### Scenario: Derived sum stays exact
- **WHEN** a derivation adds or subtracts decimal inputs
- **THEN** the result equals the exact decimal arithmetic of the inputs

### Requirement: Data-quality checks
The system SHALL run accounting-identity checks on each year's canonical sheet: balance sheet balances, equity equals common equity plus minority interest, cash-flow components sum to the change in cash, gross profit equals revenue minus cost of revenue, and similar identities applicable to the template. Each check result SHALL be `passed`, `failed` or `not_applicable`, with the cells it used and, when failed, the difference.

#### Scenario: Cash-flow identity fails
- **WHEN** Malam FY2025 has CFO + CFI + CFF = 38,856,000 and a change in cash of 3,798,000
- **THEN** the cash-flow check fails, reporting both amounts and the difference

#### Scenario: Equity identity fails
- **WHEN** Malam FY2025 has total equity 762,392,000, common equity 767,184,000 and minority interest 4,792,000
- **THEN** the equity check fails

#### Scenario: Balance sheet balances
- **WHEN** Malam FY2025 has total assets 2,626,438,000 equal to total liabilities and equity
- **THEN** the balance-sheet check passes

### Requirement: Checks are not satisfied by derivation
A check SHALL be `not_applicable` when one of its cells was derived from the very identity the check tests, or when a cell it needs is missing. Such a check SHALL NOT count as passed.

#### Scenario: Derived common equity
- **WHEN** Malam FY2023 common equity was derived as total equity − minority interest
- **THEN** the FY2023 equity check is `not_applicable`, not `passed`

### Requirement: Point-in-time canonical sheet
The canonical sheet SHALL be buildable as of a date, using only normalized values available at or before it.

#### Scenario: Value not yet available
- **WHEN** Malam's sheet is built as of a date before its FY2025 values became available
- **THEN** FY2025 is absent from the sheet
