# Spec Delta

## MODIFIED Requirements

### Requirement: Configured model roles
Model identifiers SHALL come from configuration under three roles, main, cheap and osint, and callers SHALL choose a role rather than hard-coding a model name.

#### Scenario: Swap model
- **WHEN** the main model is changed in configuration
- **THEN** all main-role calls use the new model with no code change

#### Scenario: OSINT model configured separately
- **WHEN** the osint model is set in configuration
- **THEN** OSINT research agents use that model and main-role and cheap-role calls are unchanged
