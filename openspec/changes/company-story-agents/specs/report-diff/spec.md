# Spec Delta

## Purpose

Compares a company's annual reports across fiscal years: aligns their sections and determines, deterministically, which sections changed. It is the input for explaining what changed, and the base that the full report diff later builds on.

## ADDED Requirements

### Requirement: Business sections aligned across years
For a company and an ordered list of fiscal years, the system SHALL align the business-description sections of each report by title, insensitive to section numbers and Hebrew plene/defective spelling. Each aligned section SHALL list its node id in every year where it appears.

#### Scenario: Renumbered section
- **WHEN** the risk-factors section is numbered 25 in one report and 22 in the next
- **THEN** both are aligned as the same section

#### Scenario: Spelling variant
- **WHEN** one report titles a section "שירותי" and another "שרותי"
- **THEN** both are aligned as the same section

### Requirement: Change status per section
Each aligned section SHALL get a status for each consecutive pair of years: `unchanged` when its text similarity is at or above the configured threshold, `changed` below it, `new` when it appears only in the later year, and `dropped` when it appears only in the earlier year. The similarity score SHALL be reported with the status.

#### Scenario: Unchanged section
- **WHEN** a section's text is identical in FY2024 and FY2025
- **THEN** its FY2024 to FY2025 status is `unchanged` with similarity 1.0

#### Scenario: New section
- **WHEN** a section appears in FY2025 but not in FY2024
- **THEN** its FY2024 to FY2025 status is `new`

#### Scenario: Changed section
- **WHEN** a section's similarity between FY2024 and FY2025 is below the threshold
- **THEN** its status is `changed`, with the score

### Requirement: Deterministic comparison
The comparison SHALL use no LLM and SHALL return the same alignment, statuses and scores for the same reports and configuration.

#### Scenario: Repeat run
- **WHEN** the comparison runs twice on the same three cached reports
- **THEN** both results are identical

### Requirement: Comparison from the CLI
The CLI SHALL print the comparison for a ticker and fiscal years: each aligned section with its title, its status and score per year pair, and its node ids.

#### Scenario: CLI comparison
- **WHEN** the comparison command runs for MLTM FY2023 to FY2025 in cached mode
- **THEN** every business-description section is printed with a status and score for each year pair
