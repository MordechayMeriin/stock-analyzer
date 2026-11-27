# Spec Delta

## MODIFIED Requirements

### Requirement: Research areas
The research SHALL cover eight areas: news and events; market signals; credit ratings and analyst forecasts;
operations and demand; legal proceedings; upcoming regulation; labor and government; competition, macro and
geopolitics.

#### Scenario: All areas reported
- **WHEN** a research run completes
- **THEN** the scorecard has one entry for each of the eight areas

## ADDED Requirements

### Requirement: Legal proceedings researched
The legal area SHALL cover court cases and legal proceedings involving the company, its controlling
shareholder or its managers: lawsuits and class actions, criminal or regulatory investigations and
enforcement, fines, arbitration, rulings and appeals, with their status and the amounts at stake when known.

#### Scenario: Class action against the company
- **WHEN** a class action against the company was filed or certified inside the window
- **THEN** the legal area can report it as a finding with its status and amount, citing its source

### Requirement: Upcoming regulation researched
The regulation area SHALL cover new and pending regulation affecting the company or its industry: bills,
regulator directives and drafts, reforms, licence, tariff or tax changes, each with its status (proposed,
approved, in force), its effective date when known and its expected effect on the company.

#### Scenario: Pending reform
- **WHEN** a regulator published a draft reform for the company's industry inside the window
- **THEN** the regulation area can report it with status proposed and its expected effect on the company

### Requirement: Legal and regulatory risk weighed
The scorecard SHALL weigh material legal proceedings and regulation that is approved or close to approval,
and SHALL be able to list them among the top risks.

#### Scenario: Large certified claim
- **WHEN** a large class action against the company was certified
- **THEN** the scorecard can list it among the top risks, citing the finding

### Requirement: Claims checked against their sources
Each finding that passes the URL and window checks SHALL be checked against the search excerpt the run
holds for its URL, with one of four verdicts: supported, partial, unsupported or unverified (no excerpt).
Unsupported findings SHALL be dropped and counted; partial and unverified findings SHALL be kept at low
confidence. Each kept finding SHALL carry its verdict.

#### Scenario: Claim the source does not make
- **WHEN** a finding states a figure that the excerpt of its source does not contain or support
- **THEN** the finding is dropped and the unsupported count increases by one

#### Scenario: Partly supported claim
- **WHEN** the excerpt supports part of a finding's claim but not all of it
- **THEN** the finding is kept with verdict partial and low confidence

#### Scenario: No excerpt
- **WHEN** the search returned no excerpt for a finding's URL
- **THEN** the finding is kept with verdict unverified and low confidence

### Requirement: Duplicate findings merged
Findings that describe the same event SHALL be merged into one finding, also when they come from
different areas or different sources. The merged finding SHALL keep the strongest version (supported over
partial, then higher confidence, then newer) and SHALL list the other sources and areas. The result SHALL
report how many findings were merged.

#### Scenario: Same event in two areas
- **WHEN** the news area and the competition area both report the same fine from different articles
- **THEN** the result has one finding for the fine, listing both sources and both areas, and the merged count is one

#### Scenario: Different events stay separate
- **WHEN** two findings report two different fines by the same regulator
- **THEN** both findings are kept

### Requirement: Scorecard sees each event once
The scorecard SHALL be built from the merged findings, so an event reported several times counts once.

#### Scenario: Repeated event
- **WHEN** one event was reported by three findings
- **THEN** the scorecard input contains it as a single finding

### Requirement: Trend per area and overall
Each area assessment and the overall assessment SHALL have a trend: improving, stable, deteriorating or
unclear, with a short explanation in Hebrew. An area with insufficient data SHALL have trend unclear. The
trend SHALL take into account how recent the positive and negative findings are within the window.

#### Scenario: Recent negative evidence
- **WHEN** an area's older findings are mostly positive and its findings from the last year are mostly negative
- **THEN** the system gives the scorecard this recent-versus-older split, and the area's trend is deteriorating unless its explanation says why not

#### Scenario: Area without findings
- **WHEN** an area has insufficient data
- **THEN** its trend is unclear

### Requirement: Company profile in the result
The result SHALL include the company profile built at the start of the run: the industry, main business
lines, controlling shareholder when known, main competitors, regulator, and the key drivers of stability
for that industry.

#### Scenario: Profile stored
- **WHEN** a research run completes
- **THEN** the result contains the company's industry and at least one key driver

### Requirement: Analysis focused on the industry
The scorecard SHALL rate each area's importance for the company's industry (high, medium or low) and SHALL
weigh areas by that importance in the overall label. It SHALL include a key-drivers section: for each key
driver of the industry, its current status (positive, negative, mixed or unknown), a short Hebrew
explanation and the findings it rests on.

#### Scenario: Key drivers reported
- **WHEN** a research run completes for an airline
- **THEN** the scorecard lists drivers relevant to airlines, such as demand and traffic, competition and security disruptions, each with a status and its findings

#### Scenario: Driver without evidence
- **WHEN** no kept finding concerns a key driver
- **THEN** that driver's status is unknown and it cites no findings

### Requirement: Older stored results still load
Results stored before these fields existed SHALL still load and be shown, without the new fields.

#### Scenario: Old result
- **WHEN** a stored result without verdicts, trends, profile or key drivers is read
- **THEN** it loads without error and the missing fields are empty
