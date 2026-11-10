# llm-gateway Specification

## Purpose

Provides a single, testable entry point for every LLM call: schema-validated structured output, streamed text, caching and cost accounting, with a deterministic fake so the whole system runs offline in tests.

## Requirements

### Requirement: Structured JSON completion
The system SHALL send a request (model, system prompt, user prompt, output schema, optional tools) to the configured LLM provider and SHALL return an object validated against the schema.

#### Scenario: Valid output
- **WHEN** the model returns JSON matching the schema
- **THEN** a validated object is returned

### Requirement: One repair retry
If the model's output fails to parse or validate, the system SHALL make exactly one repair request that includes the validation error. If the repaired output still fails, the call SHALL raise an error that carries the raw output.

#### Scenario: Repaired output
- **WHEN** the first output is missing a required field and the repair response is valid
- **THEN** the repaired object is returned and both attempts are logged

#### Scenario: Repair fails
- **WHEN** both attempts are invalid
- **THEN** an error is raised containing the last raw output

### Requirement: Streaming text completion
The system SHALL support a streamed text completion that yields text increments as they arrive, followed by a final event with token usage and cost.

#### Scenario: Stream to client
- **WHEN** a streamed completion is requested
- **THEN** text increments are yielded in order, and the last event reports tokens and cost

### Requirement: Response cache
Non-streamed completions SHALL be cached on disk, keyed by model, prompts, schema and parameters, and identical requests SHALL be served from the cache without a provider call.

#### Scenario: Cached completion
- **WHEN** an identical structured request is made twice
- **THEN** the second is served from the cache at zero cost

### Requirement: Cost and latency log
Every provider call SHALL append a log record with time, model, purpose label, input and output tokens, cost, latency, cache hit or miss, and success or failure.

#### Scenario: Logged call
- **WHEN** a completion finishes
- **THEN** a log record with tokens, cost and latency is appended

### Requirement: Configured model roles
Model identifiers SHALL come from configuration under two roles, main and cheap, and callers SHALL choose a role rather than hard-coding a model name.

#### Scenario: Swap model
- **WHEN** the main model is changed in configuration
- **THEN** all main-role calls use the new model with no code change

### Requirement: Fake LLM for tests
A fake LLM SHALL be available with the same interface. It returns scripted or schema-derived responses and makes no network calls, so the test suite runs offline.

#### Scenario: Offline test run
- **WHEN** the test suite runs without network access or an API key
- **THEN** every LLM-dependent test passes using the fake

### Requirement: LLM credentials from environment
The provider API key SHALL be read only from the environment and SHALL never be logged or returned to clients.

#### Scenario: Missing key
- **WHEN** a live LLM call is made without the key configured
- **THEN** it fails with an error naming the missing variable
