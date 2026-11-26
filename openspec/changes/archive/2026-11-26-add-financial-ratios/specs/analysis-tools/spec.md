# Spec Delta

## Purpose

Gives LLM agents tool calls over the system's own local data, starting with financial ratios and
canonical financials, so agents read and cite computed numbers instead of calculating them.

## ADDED Requirements

### Requirement: Tool definitions
The system SHALL provide `get_ratios` and `get_financials` as tool definitions with a name, a description and a JSON schema for their arguments, in the form the LLM gateway accepts for tool calls.

#### Scenario: Definitions for the gateway
- **WHEN** the tool definitions are requested
- **THEN** each has a name, a description and an argument schema that the LLM gateway can send with a request

### Requirement: Bound company and date
Each tool set SHALL be bound to one ticker and an optional `as_of` date when it is created. The model SHALL NOT be able to choose the ticker or the date through tool arguments.

#### Scenario: Ticker not an argument
- **WHEN** the argument schema of `get_ratios` is inspected
- **THEN** it has no ticker or date argument

#### Scenario: Point in time
- **WHEN** a tool set is bound to MLTM with an `as_of` date before FY2025 values were available
- **THEN** `get_ratios` returns no FY2025 values

### Requirement: get_ratios
`get_ratios` SHALL accept an optional ratio group and an optional list of ratio codes, and SHALL return the matching ratio series of the bound company: for each ratio its code, Hebrew name, unit and, per year, the value or missing reason, confidence, failed checks and status.

#### Scenario: One group
- **WHEN** `get_ratios` is called with group profitability for MLTM
- **THEN** only profitability ratios are returned, each with its yearly values

#### Scenario: Unknown code
- **WHEN** `get_ratios` is called with a code that is not in the registry or does not apply to the company's template
- **THEN** the tool returns an error result naming the code, which the model can read, instead of raising

### Requirement: get_financials
`get_financials` SHALL accept an optional list of canonical field names and SHALL return the bound company's canonical values per year, each with its basis.

#### Scenario: Selected fields
- **WHEN** `get_financials` is called with revenue and total assets for MLTM
- **THEN** only those two fields are returned, per fiscal year, with value and basis

### Requirement: Citable ids
Every returned value SHALL carry a stable id: `RATIO:{code}:{fiscal_year}` for ratio values and `FIN:{field}:{fiscal_year}` for canonical values, so a claim can cite exactly the number it uses.

#### Scenario: Ratio id
- **WHEN** `get_ratios` returns Malam's FY2025 gross margin
- **THEN** the value carries id `RATIO:gross_margin:2025`

### Requirement: Compact, exact output
Tool results SHALL be compact JSON with values as decimal strings and no computation left to the model, and SHALL be the same values the API and CLI return for the same inputs.

#### Scenario: Parity with the API
- **WHEN** `get_ratios` and the ratios endpoint are called for MLTM with the same `as_of`
- **THEN** every value, confidence and status matches
