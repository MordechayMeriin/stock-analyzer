# Spec Delta

## MODIFIED Requirements

### Requirement: Response cache
Non-streamed completions SHALL be cached in the server's state store, keyed by model, prompts, schema and parameters, and identical requests SHALL be served from the cache without a provider call.

#### Scenario: Cached completion
- **WHEN** an identical structured request is made twice
- **THEN** the second is served from the cache at zero cost
