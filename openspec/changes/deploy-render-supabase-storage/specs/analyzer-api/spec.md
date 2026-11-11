# Spec Delta

## MODIFIED Requirements

### Requirement: Health endpoint
The API SHALL expose an unauthenticated health endpoint that reports liveness, whether provider and LLM credentials are configured, and which state store backend is active and whether it is reachable, without revealing credentials or connection details.

#### Scenario: Health check
- **WHEN** the health endpoint is called
- **THEN** it returns status ok, plus a true or false flag for each credential

#### Scenario: Storage reported
- **WHEN** the health endpoint is called on a server using a database
- **THEN** it names the database backend and reports it as reachable, without the database URL or any part of it

#### Scenario: Storage unreachable
- **WHEN** the health endpoint is called while the database cannot be reached
- **THEN** it still answers, and it reports storage as unreachable
