# Spec Delta

## ADDED Requirements

### Requirement: Story view
The client SHALL show a company's latest saved story on its own page, linked from the company page. The page SHALL show the fiscal years covered, `as_of`, and the three sections in Hebrew. Story-versus-numbers findings SHALL be shown with their label, using text as well as colour.

#### Scenario: Open Malam's story
- **WHEN** the user opens the story page for Malam after a story was saved
- **THEN** the covered fiscal years, `as_of` and the three sections are shown, and each finding shows its label in words

#### Scenario: No story yet
- **WHEN** the user opens the story page for a company with no saved story
- **THEN** the page explains that there is no story yet and offers to generate one when live mode is allowed

### Requirement: Fact provenance in the story
Each number in the story SHALL be shown as formatted by the server, and SHALL reveal its provenance on hover or focus: the fact's name, fiscal years, exact value, inputs or operation, source filing, and confidence. Low-confidence numbers SHALL be visibly marked and SHALL list their failed checks.

#### Scenario: Hover a ratio
- **WHEN** the user hovers or focuses the operating-margin number in the story
- **THEN** its definition, input values, fiscal year and confidence are shown

#### Scenario: Low-confidence mark
- **WHEN** the story shows a low-confidence free-cash-flow number
- **THEN** the number is marked, and its provenance lists the failed check ids

### Requirement: Story citations
Each citation in the story SHALL link to its page in the original document and SHALL also link to the paragraph in the report reader.

#### Scenario: Follow a citation
- **WHEN** the user clicks a citation's reader link
- **THEN** the report reader opens at the cited fiscal year and section

### Requirement: Generate a story live
When live mode is allowed and selected, the client SHALL let the user start a story run, SHALL show its progress events as they arrive, and SHALL show the new story when the run finishes, or the error if it fails.

#### Scenario: Live generation
- **WHEN** the user starts a story run in live mode
- **THEN** progress steps appear as they happen, and the finished story replaces the previous one with its cost shown

#### Scenario: Cached mode
- **WHEN** the client is in cached mode
- **THEN** the generate action is disabled with an explanation that it needs live mode
