# deployment Specification

## Purpose

Lets the server and the web client be built, configured and deployed independently of each other from one repository, and run together locally with a single command.

## Requirements

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
All runtime settings SHALL come from environment variables with documented defaults: credentials, data directory, database URL, allowed client origins, cached-only flag, model roles and API base URL. An example environment file SHALL list every variable with no real secret values.

#### Scenario: Example env
- **WHEN** a developer copies the example environment file and fills in the two API keys
- **THEN** the server starts and serves data in live mode

#### Scenario: Database URL is optional
- **WHEN** the example environment file is used with the database URL left empty
- **THEN** the server keeps its state in the data directory

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

### Requirement: Persistent state store
The server SHALL keep all caches, fetched reports and logs in one configurable state store: a data directory that a deployment mounts as persistent storage, or a database. Whichever is configured, the cache SHALL survive restarts.

#### Scenario: Restart keeps cache with a data volume
- **WHEN** the server container restarts with the same data volume and no database URL
- **THEN** previously cached reports are served without provider calls

#### Scenario: Restart keeps cache with a database
- **WHEN** the server restarts without any volume but with the same database URL
- **THEN** previously cached reports are served without provider calls

### Requirement: Hosted deployment definition
The repository SHALL contain a declarative hosting definition that creates the API service and the static client from the repository. The API SHALL default to cached-only, and no secret values SHALL appear in the definition.

#### Scenario: Definition has no secrets
- **WHEN** the hosting definition is inspected
- **THEN** credentials and the database URL are declared as values to be entered on the host, never written in the file

#### Scenario: Cached-only by default
- **WHEN** the services are created from the definition without overrides
- **THEN** the API refuses live-mode requests

#### Scenario: Client deep link
- **WHEN** a browser opens a client route such as a company page directly by URL
- **THEN** the static host serves the client app, and the client renders that route

### Requirement: Live mode toggle without code change
On the hosted deployment, live mode SHALL be enabled and disabled only by changing the cached-only environment variable on the host, without a code change or a new commit.

#### Scenario: Enable for a demo, then disable
- **WHEN** the host's cached-only flag is set to allow live mode and the service restarts, then later set back
- **THEN** live requests are accepted while it is set, and refused again once it is set back

### Requirement: Scheduled keep-alive check
A scheduled job SHALL call the hosted API's health endpoint at least daily, so neither the API host nor the database is idled out or auto-paused for inactivity. The job SHALL fail visibly when the API is unreachable or reports storage as unreachable.

#### Scenario: Healthy run
- **WHEN** the scheduled job runs and the health endpoint reports storage as reachable
- **THEN** the job succeeds

#### Scenario: Storage down
- **WHEN** the health endpoint answers but reports storage as unreachable
- **THEN** the job fails, so the repository owner is notified
