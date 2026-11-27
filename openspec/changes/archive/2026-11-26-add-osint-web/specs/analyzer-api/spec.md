## MODIFIED Requirements

### Requirement: OSINT endpoints
The API SHALL expose OSINT research at `/api/companies/{ticker}/osint` with an optional window of 1 to 120
months (default the configured one). `GET` SHALL return the latest stored result and never search or call an
LLM, in any mode. `POST` SHALL run the research afresh in live mode through the research CLI's server function,
store it, and stream `progress` events, then one `done` event with the result or one `error` event. Refusals
SHALL come as plain JSON errors before the stream.

#### Scenario: Stored result
- **WHEN** ELAL has been researched with a 36-month window and the client requests its OSINT result in either mode
- **THEN** the stored scorecard, findings and run statistics are returned, marked as stored, and no search or LLM call is made

#### Scenario: Never researched
- **WHEN** the OSINT result of a tracked company that was never researched for the window is requested
- **THEN** a 409 is returned with code `not_cached`

#### Scenario: Untracked ticker
- **WHEN** the OSINT result of a ticker that is not tracked is requested, or a run for it
- **THEN** a 404 is returned with code `company_not_found`, and no search or LLM call is made

#### Scenario: Run refused outside live mode
- **WHEN** a research run is requested in cached mode, or on a server with live calls disabled
- **THEN** a 403 is returned with code `live_required` or `live_disabled` before any stream starts, and no search or LLM call is made

#### Scenario: Run in live mode
- **WHEN** a research run for ELAL is requested in live mode
- **THEN** the stream carries progress events (step, area, searches used, search limit) with searches used never
  above the limit, then one `done` event with the new result, which replaces the stored one for that window

#### Scenario: Run already in progress
- **WHEN** a research run is requested for a ticker and window while another run for them is still running
- **THEN** a 409 is returned with code `research_in_progress`, and the first run is not affected

#### Scenario: Client disconnects during a run
- **WHEN** the client closes the stream before the run finishes
- **THEN** the run continues and its result is stored

#### Scenario: No verified findings
- **WHEN** a run ends without any finding that survives verification
- **THEN** the stream ends with an `error` event with code `osint_no_findings`, and the previously stored result is kept

#### Scenario: Missing OpenRouter key
- **WHEN** a live run is requested and the OpenRouter key is not configured
- **THEN** a 503 is returned with code `missing_credential` before any stream starts

#### Scenario: Window out of range
- **WHEN** a result or a run is requested with a window below 1 or above 120 months
- **THEN** a 422 is returned with code `validation_error`
