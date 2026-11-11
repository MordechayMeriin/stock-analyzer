# Spec Delta

## MODIFIED Requirements

### Requirement: Environment-only configuration
All runtime settings SHALL come from environment variables with documented defaults: credentials, data directory, database URL, allowed client origins, cached-only flag, model roles and API base URL. An example environment file SHALL list every variable with no real secret values.

#### Scenario: Example env
- **WHEN** a developer copies the example environment file and fills in the two API keys
- **THEN** the server starts and serves data in live mode

#### Scenario: Database URL is optional
- **WHEN** the example environment file is used with the database URL left empty
- **THEN** the server keeps its state in the data directory

## REMOVED Requirements

### Requirement: Persistent data directory
**Reason**: Hosted platforms with ephemeral filesystems cannot keep a data directory across restarts. Persistence is now a property of the configured state store, which can be a data directory or a database.
**Migration**: Local and container runs without a database URL keep using the data directory unchanged. Hosted deployments set a database URL. See "Persistent state store" below and the `state-store` capability.

## ADDED Requirements

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
