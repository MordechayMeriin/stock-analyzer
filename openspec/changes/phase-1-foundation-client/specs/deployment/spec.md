# Spec Delta

## Purpose

Lets the server and the web client be built, configured and deployed independently of each other from one repository, and run together locally with a single command.

## ADDED Requirements

### Requirement: Independent builds
The server and the client SHALL each build, test and produce a deployable artifact from their own directory, without needing the other's source tree or toolchain.

#### Scenario: Build client alone
- **WHEN** only the client directory is built
- **THEN** a static production bundle is produced without installing Python

#### Scenario: Build server alone
- **WHEN** only the server directory is built
- **THEN** a runnable server artifact is produced without installing Node.js

### Requirement: Container images
The server SHALL have a container image that serves the API. The client SHALL have a container image that serves its static bundle. Neither image SHALL contain secrets.

#### Scenario: Image has no secrets
- **WHEN** either image is inspected
- **THEN** it contains no API keys, cache data or log files

### Requirement: Environment-only configuration
All runtime settings SHALL come from environment variables with documented defaults: credentials, data directory, allowed client origins, cached-only flag, model roles and API base URL. An example environment file SHALL list every variable with no real secret values.

#### Scenario: Example env
- **WHEN** a developer copies the example environment file and fills in the two API keys
- **THEN** the server starts and serves data in live mode

### Requirement: Persistent data directory
The server SHALL keep all caches, fetched reports and logs under one configurable data directory, so a deployment can mount it as persistent storage.

#### Scenario: Restart keeps cache
- **WHEN** the server container restarts with the same data volume
- **THEN** previously cached reports are served without provider calls

### Requirement: Cross-origin access control
The server SHALL accept browser requests only from the configured list of allowed client origins.

#### Scenario: Disallowed origin
- **WHEN** a browser request comes from an origin not in the list
- **THEN** the server sends no CORS approval, and the browser blocks the response

### Requirement: Local combined run
A single command SHALL start the server and the client together locally, with the client pointed at the server and the data directory persisted on the host.

#### Scenario: One-command start
- **WHEN** the developer runs the combined start command with a filled environment file
- **THEN** the client is reachable in a browser and loads Malam data from the server
