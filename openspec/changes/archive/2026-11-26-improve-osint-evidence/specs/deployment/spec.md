# Spec Delta

## ADDED Requirements

### Requirement: OSINT runs on the hosted API
The server image SHALL contain every file OSINT research reads at run time (the filing block-list and the
OSINT prompts), and the hosted blueprint SHALL set the OSINT settings (model, search limit, window) without
any secret value, so OSINT works on the hosted deployment as it does locally.

#### Scenario: Stored result on the hosted API
- **WHEN** live calls are disabled on the hosted API and a stored OSINT result exists in the shared store
- **THEN** the hosted API serves it

#### Scenario: Live run on the hosted API
- **WHEN** live calls are enabled on the hosted API and the OpenRouter key is set
- **THEN** a live OSINT run completes in the hosted container without missing files

#### Scenario: File missing from the image
- **WHEN** the server image definition does not copy the OSINT block-list
- **THEN** the test suite fails
