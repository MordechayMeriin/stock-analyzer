# Spec Delta

## Purpose

Assesses how stable a tracked company is from open-source intelligence (news, market signals, ratings,
analyst views, operations, labor, competition and geopolitics) without using any of its official filings.

## ADDED Requirements

### Requirement: Research run for a tracked company
The system SHALL run OSINT research for one tracked company, identified by ticker, and SHALL use the
company's tracked names to search. A ticker that is not tracked SHALL be rejected without any provider call.

#### Scenario: Tracked company
- **WHEN** a user runs research for ticker ELAL, which is tracked
- **THEN** the system searches using El Al's Hebrew and English names and returns a scorecard

#### Scenario: Unknown ticker
- **WHEN** a user runs research for a ticker that is not tracked
- **THEN** the system reports that the ticker is not tracked and makes no LLM or search call

### Requirement: Research areas
The research SHALL cover six areas: news and events; market signals; credit ratings and analyst forecasts;
operations and demand; labor and government; competition, macro and geopolitics.

#### Scenario: All areas reported
- **WHEN** a research run completes
- **THEN** the scorecard has one entry for each of the six areas

### Requirement: Filing sources excluded
Research SHALL NOT use official filings. Every web search SHALL exclude the domains and paths on a
configured block-list of the official filing systems, and any result whose URL
matches the block-list SHALL be discarded before an agent sees it.

#### Scenario: Provider returns a blocked result
- **WHEN** a search result's URL is on maya.tase.co.il, a domain on the block-list
- **THEN** the result is discarded and no finding can cite it

#### Scenario: Block-list sent with every search
- **WHEN** an agent performs a web search
- **THEN** the search request carries the block-list as excluded domains

### Requirement: No stored filing data
A research run SHALL NOT read the filings provider, stored report text or stored financial data.

#### Scenario: Run with filings in the store
- **WHEN** reports and financials for the company exist in the state store
- **THEN** the research run completes without reading them and makes no filings-provider call

### Requirement: Filing-derived news labelled
A finding whose source only restates figures from the company's filings SHALL be kept and marked as
derived from a filing.

#### Scenario: News article on quarterly results
- **WHEN** a finding comes from a news article reporting the company's quarterly profit
- **THEN** the finding is marked as derived from a filing

### Requirement: Cited findings
Each finding SHALL carry a claim, an area, a signal (positive, negative or neutral), a confidence (high,
medium or low), a source URL and the source's publish date when known.

#### Scenario: Finding fields
- **WHEN** a specialist reports a finding
- **THEN** the finding has a claim, area, signal, confidence and source URL

### Requirement: Citations verified against searches
A finding SHALL be kept only if its source URL was returned by a web search during the same run. Other
findings SHALL be dropped and counted in the run result.

#### Scenario: Invented URL
- **WHEN** a specialist cites a URL that no search in the run returned
- **THEN** the finding is dropped and the dropped count increases by one

### Requirement: Research window
Research SHALL describe the company as of the run date and its trend over a time window that defaults to
the last 36 months and can be changed per run. Findings with a known publish date outside the window SHALL
be dropped.

#### Scenario: Default window
- **WHEN** a run is started without a window
- **THEN** only findings published in the last 36 months are kept

#### Scenario: Old article
- **WHEN** a finding's publish date is four years before the run with a 36-month window
- **THEN** the finding is dropped

### Requirement: Stability scorecard
The run SHALL return a scorecard with a label per area and overall, each one of stable, watch or fragile, the
top three risks and strengths, and a summary in Hebrew. No numeric score SHALL be given.

#### Scenario: Scorecard contents
- **WHEN** a research run completes
- **THEN** the result has an overall label, a label for each area, up to three risks, up to three strengths and a Hebrew summary

### Requirement: Claims in the scorecard are cited
Every risk, strength and area assessment in the scorecard SHALL reference at least one kept finding.

#### Scenario: Risk with sources
- **WHEN** the scorecard lists a risk
- **THEN** the risk references one or more findings with their source URLs

### Requirement: Areas without evidence
An area with no kept findings SHALL be reported as having insufficient data instead of receiving a label.

#### Scenario: Empty area
- **WHEN** no finding is kept for the labor and government area
- **THEN** that area is reported as insufficient data

### Requirement: Search budget per run
The number of web searches in one run SHALL NOT exceed a configured limit. When the limit is reached, further
searches SHALL return an error the agent can read, and the run SHALL still produce a scorecard from the
findings so far.

#### Scenario: Limit reached
- **WHEN** a run has used its configured number of searches and an agent asks for another
- **THEN** the search is refused, no provider call is made, and the run still returns a scorecard

### Requirement: Every live run is fresh
When live calls are allowed, every research run SHALL search the web afresh; a stored result SHALL NOT be
returned instead.

#### Scenario: Repeat run
- **WHEN** research for ELAL with the same window is run twice on the same day in live mode
- **THEN** both runs search the web and the second result is not marked as stored

### Requirement: Latest result stored
Each completed run's result SHALL be stored in the state store as the latest result for its ticker and
window, replacing the previous one.

#### Scenario: Stored after a run
- **WHEN** a live run for ELAL with a 36-month window completes
- **THEN** the stored latest result for ELAL and 36 months is that run's result

### Requirement: Live calls respect the live-mode switch
When live provider calls are disabled, a research run SHALL return the latest stored result if one exists and SHALL
otherwise fail without any LLM or search call.

#### Scenario: Live calls disabled, nothing stored
- **WHEN** live calls are disabled and no stored result exists for the request
- **THEN** the run fails with a message that live calls are disabled and no provider call is made

### Requirement: Research usage logged
Every LLM call and web search in a research run SHALL append a usage record with model, purpose, tokens,
cost, latency and success, in the same usage log as other LLM calls.

#### Scenario: Usage after a run
- **WHEN** a research run completes
- **THEN** the usage log has records with an OSINT purpose for the agent calls and the searches

### Requirement: Research CLI command
The CLI SHALL provide a command that runs research for a ticker, with options for the window in months
and JSON output, and SHALL print the scorecard with its sources.

#### Scenario: Run from the CLI
- **WHEN** a user runs `stock-analyzer osint ELAL`
- **THEN** the CLI prints the overall label, the area labels, risks, strengths and the source URLs

#### Scenario: JSON output
- **WHEN** a user runs the command with the JSON option
- **THEN** the CLI prints the full result as JSON

### Requirement: Offline research for tests
With the fake LLM enabled, a research run SHALL complete using scripted agent replies and scripted search
results, with no network call.

#### Scenario: Fake mode
- **WHEN** a research run is started with the fake LLM enabled
- **THEN** it returns a scorecard and makes no network request
