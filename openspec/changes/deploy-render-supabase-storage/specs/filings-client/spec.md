# Spec Delta

## MODIFIED Requirements

### Requirement: Permanent response cache
Every successful provider response SHALL be cached in the server's state store, keyed by request path and parameters, and reused on later identical requests without contacting the provider. A refresh option SHALL bypass and overwrite the cache.

#### Scenario: Repeat request
- **WHEN** the same request is made twice
- **THEN** the second request is served from the cache and uses no credits

#### Scenario: Forced refresh
- **WHEN** a request is made with refresh enabled
- **THEN** the provider is called and the cached entry is replaced

#### Scenario: Offline mode
- **WHEN** the system runs in cached-only mode and a request is not cached
- **THEN** it fails with a "not cached" error and makes no network call

#### Scenario: Cache outlives the server process
- **WHEN** a response was cached by one server or CLI process and another process with the same store makes the same request
- **THEN** it is served from the cache and uses no credits
