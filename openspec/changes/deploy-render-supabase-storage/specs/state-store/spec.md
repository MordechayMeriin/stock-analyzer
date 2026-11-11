# Spec Delta

## Purpose

Decides where the server keeps its durable state: provider and LLM response caches, fetched reports, financials snapshots and usage logs. Keeps that state intact and private whether it lives in a local data directory or in a hosted database.

## ADDED Requirements

### Requirement: Backend chosen by configuration
The server SHALL keep its state in a database when a database URL is configured, and in the data directory otherwise. The choice SHALL come only from configuration, with no code change.

#### Scenario: No database configured
- **WHEN** the server starts without a database URL
- **THEN** caches, reports, financials snapshots and logs are read from and written to the data directory, exactly as before

#### Scenario: Database configured
- **WHEN** the server starts with a database URL
- **THEN** caches, reports, financials snapshots and logs are read from and written to the database, and nothing is written to the data directory

### Requirement: All server state in one store
The provider response cache, the LLM response cache, fetched report text with its metadata, saved financials snapshots, and the provider and LLM usage logs SHALL all be kept in the active backend.

#### Scenario: Fetch writes everything to the database
- **WHEN** a report is fetched in live mode with a database configured
- **THEN** the provider responses, the report text and metadata, the financials snapshots and the usage log records are all in the database

### Requirement: Same behavior on every backend
Reading, writing, cache hits and misses, cached-only refusals and usage totals SHALL behave the same on both backends for the same sequence of operations.

#### Scenario: Cache hit on either backend
- **WHEN** the same provider request is made twice on either backend
- **THEN** the second request is served from the store, makes no provider call and is logged as a cache hit

#### Scenario: Exact report text
- **WHEN** a report is saved and loaded again on either backend
- **THEN** the loaded text is byte-identical to the saved text, including line endings and Hebrew characters

### Requirement: State survives redeploys
With a database configured, cached data SHALL survive server restarts, redeploys and replacement of the server's filesystem.

#### Scenario: Redeploy on an ephemeral filesystem
- **WHEN** the server is redeployed onto a fresh filesystem with the same database URL
- **THEN** previously fetched reports are served in cached mode without provider calls

### Requirement: Shared store across server instances
Server instances and CLI runs configured with the same database URL SHALL see each other's writes.

#### Scenario: Populate from the CLI, serve from the API
- **WHEN** a developer fetches a report live from the CLI against the hosted database
- **THEN** a cached-only API server using the same database serves that report

### Requirement: Database state not publicly reachable
Database tables holding server state SHALL NOT be readable or writable through the database provider's public data APIs or anonymous keys. Only the server's own connection SHALL reach them.

#### Scenario: Anonymous API access
- **WHEN** the database provider's public REST API is queried with the project's anonymous key
- **THEN** none of the server's state tables can be listed, read or written

### Requirement: Explicit schema setup
The database schema SHALL be created by an idempotent setup command. A server configured for a database whose schema is missing SHALL fail with an error naming that command.

#### Scenario: Re-running setup
- **WHEN** the setup command runs against a database that already has the schema
- **THEN** it succeeds and leaves existing data unchanged

#### Scenario: Schema missing
- **WHEN** the server uses a database that has no schema yet
- **THEN** the error says the schema is missing and names the setup command

### Requirement: Database credentials from environment
The database URL SHALL be read only from the environment and SHALL never appear in logs, API responses, cache entries or error messages.

#### Scenario: Unreachable database
- **WHEN** the database cannot be reached
- **THEN** the error says storage is unreachable without including the URL, user name or password
