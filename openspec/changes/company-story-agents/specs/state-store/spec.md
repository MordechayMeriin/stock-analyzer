# Spec Delta

## ADDED Requirements

### Requirement: Saved story runs in the store
Story runs SHALL be kept in the active backend: saving a run, reading a company's latest run, and listing a company's runs newest first. A saved run SHALL be read back exactly as written, on both backends.

#### Scenario: Round trip on either backend
- **WHEN** a story run is saved and read back on either backend
- **THEN** the loaded run equals the saved run, including Hebrew text and decimal strings

#### Scenario: Latest run
- **WHEN** two runs are saved for the same company
- **THEN** reading the latest run returns the second one, and listing returns both, newest first

#### Scenario: Shared with the API
- **WHEN** a story run is generated from the CLI against the hosted database
- **THEN** a cached-only API server using the same database returns it as the latest story
