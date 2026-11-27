# Spec Delta

## Purpose

Turns a company's saved story run into the company report the web report screen shows: a
five-axis score profile per fiscal year, a breakdown for each axis, events and key metrics.
The story is what gets judged, and the run's facts are the evidence.

## ADDED Requirements

### Requirement: Report built from a saved story run
The system SHALL build a company's report from its latest saved story run. It SHALL NOT call the filings provider and SHALL NOT re-run the story. The report's fiscal years SHALL be the run's years, oldest first.

#### Scenario: El Al report from its story run
- **WHEN** a report is built for ELAL and its latest story run covers 2023, 2024 and 2025
- **THEN** the report's `years` is `[2023, 2024, 2025]` and no provider credits are spent

#### Scenario: No story run
- **WHEN** a report is requested for a ticker with no saved story run
- **THEN** the request fails as not cached, and the message says to generate the story first

### Requirement: Five story-based axes
The profile SHALL have exactly these axes, in this order: `stability`, `safety`, `revenue_quality`, `growth`, `profitability`. Their Hebrew labels SHALL be יציבות, ביטחון, איכות הכנסות, צמיחה and רווחיות. `safety` SHALL mean the opposite of risk. A higher score SHALL always be better.

#### Scenario: Axis set
- **WHEN** any report is built
- **THEN** `profile.axes` has the five ids above in that order, each label at most 16 characters

### Requirement: Scores judged from the story
Each axis SHALL get one score per fiscal year: a whole number from 1 to 10, judged mainly from the story's narrative and findings. Each score SHALL cite one or more fact ids from the run as its evidence. The score SHALL be `null` when the story and its facts give no basis for that axis and year, and then the axis status SHALL be `insufficient_data`.

#### Scenario: Story overrides strong ratios
- **WHEN** the story says a year's revenue peak rested on abnormal market conditions
- **THEN** that year's `stability` and `revenue_quality` scores reflect the story, even if the ratios alone look strong

#### Scenario: No basis for a year
- **WHEN** the story and its facts say nothing relevant to an axis for a fiscal year
- **THEN** that score's `value` is `null`, never 0, and the axis status is `insufficient_data`

### Requirement: Scores verified against the run
Before a report is saved, the system SHALL reject rater output in any of these cases: it cites a fact id that is not in the run's facts; a score is outside 1-10 and not `null`; a year or axis is missing; or a label is longer than the contract allows. On rejection, the system SHALL send the errors back to the rater once. If the output still fails, the request SHALL fail without saving a report.

#### Scenario: Unknown fact id
- **WHEN** the rater cites `RATIO:roe:2019`, which is not in the run
- **THEN** the output is rejected and the error names that id

#### Scenario: Second failure
- **WHEN** the corrected output still fails verification
- **THEN** the request fails with an error and no report is saved

### Requirement: Trends and drivers
For each score after the first year shown, the report SHALL include a trend: the direction and delta from the previous year's score, and a tone (positive when the score went up). The first year's trend SHALL be `null`. When both scores exist, each score SHALL have a driver label of at most 28 characters taken from the rater.

#### Scenario: Score fell
- **WHEN** `growth` is 9 in 2024 and 3 in 2025
- **THEN** the 2025 trend is `{direction: "down", delta: -6, tone: "negative"}`

### Requirement: Axis detail per year
For each axis and fiscal year with a score, the system SHALL provide a detail containing: a headline (at most 80 characters); up to five factors, each a label, a display value and a tone; and a plain-text explanation of at most 600 characters. Each factor's display value SHALL come from a cited fact's rendered value.

#### Scenario: Factor values come from facts
- **WHEN** the 2025 `profitability` detail lists operating margin
- **THEN** its display value is the run's rendered value of `RATIO:operating_margin:2025`

### Requirement: Events and key metrics from the run
The report SHALL list events the story describes (for example regulatory steps, wars and financing), each with a type, a date, a title of at most 40 characters and an importance from 1 to 3. Key metrics SHALL be built from the run's FIN and RATIO facts. At minimum they SHALL include revenue, operating margin, net income and operating cash flow, in the run's currency, with a null value where a year's fact is missing.

#### Scenario: Missing metric year
- **WHEN** the run has no value for a key metric in 2023
- **THEN** that metric's 2023 point has `value: null`

### Requirement: No sector comparison yet
Every score's `sector_median` SHALL be `null`, and no axis detail SHALL include a sector comparison.

#### Scenario: Sector median
- **WHEN** any report is built
- **THEN** every `sector_median` is `null`

### Requirement: Report saved per story run
A built report SHALL be saved and keyed by its story run id. A later request for the same run SHALL return the saved report unchanged, without an LLM call. A newer story run SHALL produce a new report.

#### Scenario: Repeat request
- **WHEN** the ELAL report is requested twice for the same story run
- **THEN** the second response is identical and costs nothing
