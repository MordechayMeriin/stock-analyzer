# Spec Delta

## ADDED Requirements

### Requirement: Web citations in the story
The story page SHALL show web citations apart from report citations, in a style that does not rely on colour alone. Each web citation SHALL show the source's title and publish date, or that the date is unknown, and SHALL open the source URL in a new tab.

#### Scenario: Paragraph with both kinds of citation
- **WHEN** a story paragraph cites a report paragraph and a news source
- **THEN** the report citation opens the document page, and the web citation is marked as a web source, shows its title and date, and opens the article in a new tab

#### Scenario: Undated source
- **WHEN** a cited web source has no known publish date
- **THEN** its citation says that the date is unknown

### Requirement: Web number provenance
Each number quoted from a web source SHALL be marked as a press number. On hover or focus it SHALL show its exact value and currency, the source title and date, the quoted text with the excerpt it was found in, and a note that it is not audited.

#### Scenario: Hover a web number
- **WHEN** the user hovers or focuses a tender amount quoted from a news article
- **THEN** the provenance shows the value, its currency, the article title and date, the quoted text in its excerpt, and that the number is not audited

## MODIFIED Requirements

### Requirement: Generate a story live
When live mode is allowed and selected, the client SHALL let the user start a story run, SHALL show its progress events as they arrive, including OSINT research progress and the storyteller's searches left, and SHALL show the new story when the run finishes, or the error if it fails.

#### Scenario: Live generation
- **WHEN** the user starts a story run in live mode
- **THEN** progress steps appear as they happen, and the finished story replaces the previous one with its cost shown

#### Scenario: Cached mode
- **WHEN** the client is in cached mode
- **THEN** the generate action is disabled with an explanation that it needs live mode

#### Scenario: Research started by the story
- **WHEN** a live story run starts an OSINT research run
- **THEN** the progress shows the research run and each area as it finishes, before the storyteller starts

#### Scenario: Search limit exceeded
- **WHEN** a live story run fails because the storyteller asked for more searches than the limit
- **THEN** the page shows the error with the limit, and the previous story stays shown
