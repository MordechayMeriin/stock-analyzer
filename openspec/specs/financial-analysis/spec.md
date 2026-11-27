# financial-analysis Specification

## Purpose

Deterministic analysis on top of normalized financial values: core ratios, year-over-year changes, and data-quality checks that mark which figures can be trusted. It uses no LLM, and every result is traceable to its inputs.

## Requirements

### Requirement: Core ratio registry
The system SHALL compute a fixed registry of core ratios per fiscal year from normalized values: gross, operating, EBITDA and net margin; free cash flow (operating cash flow plus capital expenditure, which is negative) and free-cash-flow margin; operating cash flow to consolidated net income; debt to equity; net debt to EBITDA; equity to assets; short-term share of debt; current ratio; and cash ratio.

#### Scenario: Malam FY2025 ratios
- **WHEN** core ratios are computed from the Malam FY2025 fixture
- **THEN** gross margin is 10.47%, operating margin 5.30%, EBITDA margin 7.91%, net margin 1.79%, current ratio 1.18, cash ratio 0.37, debt to equity 0.90, net debt to EBITDA 0.60, equity to assets 29.0%, short-term share of debt 64.7%, free cash flow 65.5M ₪ and free-cash-flow margin 1.58%, each at the precision shown

### Requirement: Exact ratio values with inputs
Each ratio value SHALL be an exact decimal computed without binary floating point, and SHALL record the codes and values of its inputs. A ratio whose input is missing, or whose denominator is zero or not meaningful (such as a negative equity base), SHALL have no value and a reason.

#### Scenario: Missing input
- **WHEN** EBITDA is missing for a fiscal year
- **THEN** EBITDA margin and net debt to EBITDA for that year have no value, with a reason naming the missing input

#### Scenario: Zero denominator
- **WHEN** current liabilities are zero
- **THEN** the current ratio has no value, with a reason

### Requirement: Year-over-year changes
The system SHALL compute the change of each normalized value and each core ratio between consecutive fiscal years. Normalized values and monetary ratios SHALL use the percent change (current − previous) ÷ |previous|; percentage ratios SHALL use the difference in percentage points; multiples SHALL use the plain difference. No change SHALL be given when either value is missing, and no percent change when the previous value is zero or the sign changes.

#### Scenario: Revenue change
- **WHEN** Malam revenue is 4,138,004,000 ₪ in FY2025 and 3,781,339,000 ₪ in FY2024
- **THEN** the FY2024 to FY2025 revenue change is 9.43% when rounded to two decimals

#### Scenario: Margin change in points
- **WHEN** gross margin is 10.47% in FY2025 and 10.60% in FY2024
- **THEN** the change is −0.13 percentage points, not a percent change

#### Scenario: Sign change
- **WHEN** net income is a loss in one year and a profit in the next
- **THEN** no change value is given, with a reason

#### Scenario: Margin from zero
- **WHEN** operating margin is 0% in one year and 5% in the next
- **THEN** the change is +5 percentage points

### Requirement: Data-quality checks
Before ratios are used, the system SHALL run a fixed set of accounting-identity checks per fiscal year, each with a stable id and a tolerance from configuration: balance-sheet checks BS1 to BS5, income-statement checks IS1 to IS3 and cash-flow checks CF1 and CF2, as defined in plan.md §3.2.

#### Scenario: Malam FY2025 failures
- **WHEN** the checks run on the Malam FY2025 fixture
- **THEN** CF1, CF2, IS3, BS4 and BS5 fail, and the other checks pass

#### Scenario: Check result detail
- **WHEN** a check fails
- **THEN** its result gives the check id, the fiscal year, the input codes and values, the expected and actual amounts, and the tolerance used

#### Scenario: Missing check input
- **WHEN** an input of a check is missing
- **THEN** that check is reported as not run, not as passed

### Requirement: Confidence from checks
Every ratio and every change SHALL carry a confidence of `high` or `low`. It SHALL be `low` when any of its inputs, directly or through another ratio, appears in a failed check for the same fiscal year, and SHALL list those check ids.

#### Scenario: Free cash flow on failed cash-flow check
- **WHEN** CF1 fails for Malam FY2025
- **THEN** FY2025 free cash flow and free-cash-flow margin have low confidence and list CF1

#### Scenario: Unaffected ratio
- **WHEN** IS1 passes for FY2025 and no other failed check involves revenue, cost of revenue or gross profit
- **THEN** FY2025 gross margin has high confidence

### Requirement: Analysis from the CLI
The CLI SHALL print, for a ticker, the core ratios per fiscal year with their changes and confidence, and the check results with each failure's detail.

#### Scenario: CLI ratios
- **WHEN** the ratios command runs for MLTM in cached mode
- **THEN** each core ratio is printed per fiscal year, low-confidence values are marked with their check ids, and failed checks are listed
