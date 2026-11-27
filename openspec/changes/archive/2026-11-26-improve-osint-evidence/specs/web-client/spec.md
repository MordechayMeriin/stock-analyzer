# Spec Delta

## ADDED Requirements

### Requirement: OSINT industry focus shown
The OSINT view SHALL show the company profile (industry and business lines) and the key-drivers section,
each driver with its status, explanation and links to its findings, before the area details.

#### Scenario: Profile and drivers
- **WHEN** a user opens the OSINT view of a result that has a profile and key drivers
- **THEN** the industry and each key driver with its status are shown, and each driver's finding ids link to the numbered sources

### Requirement: OSINT trend and importance shown
The OSINT view SHALL show the trend of each area and of the overall assessment, and each area's importance
for the industry.

#### Scenario: Area row
- **WHEN** a user looks at an area in the OSINT view
- **THEN** its label, importance and trend (improving, stable, deteriorating or unclear) are shown

### Requirement: OSINT verdicts and merged sources shown
Each numbered source in the OSINT view SHALL show its verdict (supported, partial or unverified) and, for a
merged finding, the other sources that reported the same event.

#### Scenario: Merged finding
- **WHEN** a finding was merged from three sources
- **THEN** the view shows its main source and links to the two other sources

### Requirement: Older OSINT results shown without new sections
The OSINT view SHALL show results that lack the new fields, leaving out the sections they would fill.

#### Scenario: Result from before the change
- **WHEN** the stored result has no profile, trends or verdicts
- **THEN** the view shows the scorecard as before, without empty sections or errors
