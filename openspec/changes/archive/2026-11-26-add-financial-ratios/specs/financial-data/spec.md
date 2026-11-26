# Spec Delta

## ADDED Requirements

### Requirement: Company template
Normalization SHALL keep the provider's statement template for the company (for example `industrial`, `bank` or `insurer`) alongside its normalized values, and SHALL report it as unknown when the provider gives none.

#### Scenario: Bank template
- **WHEN** Leumi's financials are normalized
- **THEN** the result carries template `bank`

#### Scenario: Template missing
- **WHEN** a cached financials response has no template field
- **THEN** the result carries template unknown, and the normalized values are unaffected
