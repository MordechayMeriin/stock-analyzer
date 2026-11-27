# Market research

## Purpose

Use a tracked issuer's industry to research the broader market through cited public evidence.

## ADDED Requirements

### Requirement: Ticker resolves the industry

The production CLI SHALL accept a tracked ticker and use the issuer's FinancialFilings ISIC Rev. 5 class code. If the ticker is unknown, it SHALL fail before provider access. If the profile has no class, it SHALL report `missing_sub_industry` before web searches.

#### Scenario: Ticker with a class

- **WHEN** an analyst requests market research for a tracked ticker whose company profile gives class 6220
- **THEN** the report identifies the ticker and class 6220

#### Scenario: Missing classification

- **WHEN** the profile lacks a class code
- **THEN** the CLI reports the missing classification and issues zero research searches

### Requirement: Market scope

Research SHALL cover Israel, Europe, and the United States by default, accept an explicit subset of those markets and a positive time window, and report the requested markets, class, and dates. It SHALL consider listed and private operators.

#### Scenario: Default coverage

- **WHEN** an analyst requests research for a tracked ticker without market options
- **THEN** the brief covers Israel, Europe, and the United States, with findings or an evidence gap for each

#### Scenario: Narrow the request

- **WHEN** an analyst requests Europe and the United States explicitly
- **THEN** the run researches those two markets

### Requirement: Geographic and statistical comparability

Findings SHALL identify the geography they describe. Quantitative comparisons SHALL use compatible geography, class coverage, periods, and units. Unmapped or broader statistics SHALL be labelled as context.

#### Scenario: European source with limited coverage

- **WHEN** a statistic covers only EU member states or one European country
- **THEN** the brief identifies that coverage and uses the figure only within that scope

#### Scenario: Broader local statistic

- **WHEN** a source reports an aggregate under a different classification or at a broader level
- **THEN** the brief labels its original scope and uses it as context unless a documented mapping supports an exact match

### Requirement: Cited industry brief

The CLI SHALL provide a brief and JSON output covering demand and growth, participants and competition, and regulation and risks. Claims SHALL cite sources returned by searches in the run. Sections with insufficient evidence SHALL say so, and market concentration claims SHALL cite evidence about market definition and shares.

#### Scenario: A private operator joins the picture

- **WHEN** an in-scope search source documents a private operator serving the market
- **THEN** the brief can identify the operator and cite that evidence

### Requirement: Research safeguards

Research SHALL use the OSINT source exclusions, citation checks, and search budget. It SHALL respect live access settings and make no financial statement, filing, or report-text requests. Cached results SHALL be keyed by ticker, normalized market set, and window, with offline test results isolated from live results.

#### Scenario: Replay the same scope

- **WHEN** a cached read requests the same ticker, set of markets and window as a saved run
- **THEN** it serves that result without provider requests

#### Scenario: Offline class fixture

- **WHEN** an offline test supplies a fixed class and scripted search results to the research service
- **THEN** it produces a deterministic brief without network access
