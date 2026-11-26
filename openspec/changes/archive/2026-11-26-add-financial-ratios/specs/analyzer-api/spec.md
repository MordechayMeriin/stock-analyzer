# Spec Delta

## ADDED Requirements

### Requirement: Ratios endpoint
The API SHALL return a company's ratio series, grouped, for an optional `as_of` date, with the company's template, currency and fiscal years. Every ratio value and input SHALL be serialized as an exact decimal string. The endpoint SHALL call the same server function as the ratios CLI command.

#### Scenario: Malam ratios
- **WHEN** the ratios of MLTM are requested in cached mode
- **THEN** the response carries template `industrial`, the fiscal years, and ratio series grouped by group, each value a decimal string or missing with a reason

#### Scenario: Low-confidence value
- **WHEN** a ratio value in the response depends on a failed data-quality check
- **THEN** that value has confidence `low` and lists the failed check ids

#### Scenario: Financials not cached
- **WHEN** a cached-mode request asks for ratios of a company whose financials are not cached
- **THEN** the API answers with the "not cached" error, and no provider call is made

#### Scenario: Unsupported template
- **WHEN** ratios are requested for a company whose template has no canonical fields
- **THEN** a 422 is returned with code `template_not_supported`, naming the template
