# Web client delta

## ADDED Requirements

### Requirement: Peer comparison view

The company page SHALL link to a peer view with controls for fiscal year, peer limit and optional foreign countries. The view SHALL align target and peer values by statement, line-item code, and fiscal year, display each issuer's reporting currency, show missing values, and explain empty peer results.

#### Scenario: Different reporting currencies

- **WHEN** the target reports ILS amounts and an international peer reports EUR amounts
- **THEN** the table shows both original currencies and values and omits cross-currency rankings

#### Scenario: Target financials unavailable

- **WHEN** peer financials are available and the target's financials are missing from cache
- **THEN** the view shows peer data and marks the target's values unavailable

### Requirement: Industry market research view

The company page SHALL link to a market research view with controls for market selection and time window. The view SHALL render each requested market's brief with source links, evidence gaps, and actual source coverage.

#### Scenario: Regional evidence gap

- **WHEN** the saved brief contains EU-only evidence and no findings for the United States
- **THEN** it labels the EU-only evidence and shows the US evidence gap

### Requirement: Explicit live research actions

The peer and market views SHALL read cached data when opened. They SHALL require an explicit user action to start a live fetch or run and SHALL explain when live access is unavailable.

#### Scenario: Opening the views in live mode

- **WHEN** the user navigates to either view while global live mode is enabled
- **THEN** the page reads cached data until the user explicitly starts a live request
