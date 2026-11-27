# Spec Delta

## ADDED Requirements

### Requirement: Agent model calls through the gateway
Every model call made by an agent run SHALL go through the gateway: the model comes from a configured role, the response is cached in the state store keyed by model, instructions, conversation input, tool definitions and output schema, and the call is logged like any other completion with a purpose label naming the agent.

#### Scenario: Agent turn logged
- **WHEN** an agent makes a model call that is not cached
- **THEN** one log record is appended with the model, the agent's purpose label, tokens, cost, latency and a cache miss

#### Scenario: Agent rerun from cache
- **WHEN** an agent run is repeated with identical inputs and tools returning identical results
- **THEN** every model call is served from the cache at zero cost, and the run produces the same output

### Requirement: No external agent tracing
Agent runs SHALL NOT send traces, prompts or outputs to any service other than the configured LLM provider.

#### Scenario: Live agent run
- **WHEN** an agent run makes live model calls
- **THEN** the only outbound requests are to the configured LLM provider

### Requirement: Fake agent model for tests
A fake agent model SHALL be available that returns scripted responses, including tool calls followed by a final structured output, with no network calls, so that agent pipelines run offline in tests.

#### Scenario: Scripted tool loop
- **WHEN** a test scripts a tool call followed by a final output
- **THEN** the agent runs the real tool, receives its result, and returns the scripted final output without network access

### Requirement: Agent turn limit
Each agent run SHALL have a configured maximum number of model turns. A run that reaches it without a final output SHALL fail with an error naming the agent.

#### Scenario: Endless tool calls
- **WHEN** an agent keeps calling tools past its turn limit
- **THEN** the run fails with an error naming the agent and the limit
