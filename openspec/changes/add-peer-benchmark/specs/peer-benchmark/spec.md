## ADDED Requirements

### Requirement: Peer matching parameter is explicit
The benchmark SHALL report the matching parameter (the ISIC `sub_industry` class), the target's code and label, and for each cohort the classification level actually used.

#### Scenario: Target code shown
- **WHEN** the benchmark for MLTM is requested
- **THEN** the response includes MLTM's ISIC code and label and the match level of each cohort

#### Scenario: Missing class
- **WHEN** the target profile has no sub-industry
- **THEN** the response carries reason `missing_sub_industry` and no peers

### Requirement: Curated peers with sub-industry fallback
When the tracked company has a curated peer list, the benchmark SHALL use exactly those peers, grouped by market. Otherwise it SHALL select peers per market by exact ISIC sub-industry match. Each cohort SHALL report its source as `curated` or `sub_industry`.

#### Scenario: Curated list present
- **WHEN** MLTM has curated peers Accenture, Capgemini and Sopra Steria
- **THEN** the US cohort contains Accenture, the EU cohort contains Capgemini and Sopra Steria, and both report source `curated`

#### Scenario: No curated list
- **WHEN** a tracked company has no curated list
- **THEN** its cohorts come from the exact sub-industry match and report source `sub_industry`

### Requirement: Per-market cohorts with ratios and medians
The benchmark SHALL return the target's ratios and, for each market cohort (default IL, US, EU), each peer's ratios over the same fiscal-year window, plus each ratio's median and count over comparable peers (same statement template).

#### Scenario: Peer on another template
- **WHEN** a peer uses the bank template and the target is industrial
- **THEN** the peer is listed with its template and excluded from medians

#### Scenario: Peer without stored financials
- **WHEN** a peer's financials are not stored
- **THEN** it is listed with status `financials_not_cached` and excluded from medians

### Requirement: Cached read makes no provider calls
`GET /api/companies/{ticker}/peer-benchmark` SHALL serve stored data only, in either mode, and SHALL return `not_cached` (409) when the peer directory is not stored.

#### Scenario: Stored data
- **WHEN** MLTM and its peer directory pages are stored
- **THEN** the endpoint returns the benchmark and logs zero credits

### Requirement: Live run announces cost
`POST /api/companies/{ticker}/peer-benchmark` SHALL require live mode. Unless the request is confirmed, it SHALL return the number of uncached financials requests and the estimated credits without fetching. When confirmed, it SHALL fetch at most the configured cap per run.

#### Scenario: Estimate first
- **WHEN** four peers lack financials and the request is not confirmed
- **THEN** the response reports `estimated_credits: 160` and no financials request is made

#### Scenario: Cached-only server
- **WHEN** the server allows cached mode only
- **THEN** the request is refused with `live_required` or `live_disabled`
