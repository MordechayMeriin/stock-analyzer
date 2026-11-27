# company-story Specification

## Purpose

Writes, verifies and renders a Hebrew story of a tracked company from its last three annual reports: what it does, what changed, and how that story fits the numbers. Every number in the story comes from code, never from the LLM.

## Requirements

### Requirement: Reports covered by a story
A story SHALL cover the three most recent fiscal years whose selected annual report was published on or before the story's `as_of` date (default: today). Reports published after `as_of` SHALL NOT be used. If fewer than three such reports are available, the request SHALL fail with an error naming the missing fiscal years.

#### Scenario: Default as_of
- **WHEN** a story for Malam is requested with no `as_of`, and its FY2023, FY2024 and FY2025 reports are available
- **THEN** the story covers FY2023, FY2024 and FY2025

#### Scenario: Future report excluded
- **WHEN** a story is requested with an `as_of` earlier than the FY2025 report's publication time
- **THEN** the FY2025 report is not used, and the story covers the three fiscal years before it

#### Scenario: Not enough reports
- **WHEN** only two annual reports are published on or before `as_of`
- **THEN** the request fails with an error naming the missing fiscal year, and no LLM call is made

### Requirement: Story sections
A story SHALL contain three sections in Hebrew: what the company does (from the latest report), what changed across the three fiscal years, and how the story fits the numbers.

#### Scenario: Complete story
- **WHEN** a story run succeeds
- **THEN** it contains the three sections, each with at least one paragraph of Hebrew text

### Requirement: Story-versus-numbers findings
The story-versus-numbers section SHALL be a list of findings. Each finding SHALL be labelled `consistent`, `tension` or `unexplained`, and SHALL cite at least one fact and at least one report paragraph.

#### Scenario: Labelled finding
- **WHEN** management attributes revenue growth to a segment, and that segment's share of revenue fell
- **THEN** the finding is labelled `tension` and cites the revenue facts and the directors'-report paragraph making the claim

#### Scenario: Finding without a fact
- **WHEN** a finding cites only report paragraphs and no fact
- **THEN** verification rejects the story

### Requirement: Numbers come only from facts
Story text written by the LLM SHALL NOT contain numerals other than the fiscal years covered by the story. Every quantity SHALL appear as a fact token that code replaces with the formatted value.

#### Scenario: Token rendered
- **WHEN** the story text contains the token for Malam's FY2025 revenue
- **THEN** the displayed story shows 4,138 מיליון ₪ formatted by code, and the token links to that fact with its exact value 4,138,004,000 ₪

#### Scenario: Stray numeral
- **WHEN** the LLM writes "הכנסות של 4.1 מיליארד" as plain text
- **THEN** verification rejects the story for a numeral outside a fact token

### Requirement: Fact registry
Each story run SHALL keep a registry of the facts available to it: normalized financial values, year-over-year changes, core ratios, numbers quoted from report text, and derived values. Each fact SHALL have a stable id, an exact decimal value or none, a unit, the fiscal years it covers, its input fact ids, and its confidence with any failed check ids.

#### Scenario: Change fact
- **WHEN** the registry is built for Malam FY2023 to FY2025
- **THEN** it contains a revenue change fact for FY2024 to FY2025 whose inputs are the two revenue values

### Requirement: Numbers quoted from report text
A number that appears only in report text (such as backlog or employee count) SHALL enter the registry only by quoting it: the agent gives a paragraph id and the exact number string, and code checks that the string appears in that paragraph and parses it, with its unit and scale, into a fact citing the paragraph. A quote that is not found SHALL be refused.

#### Scenario: Backlog quoted
- **WHEN** an agent quotes a backlog figure with the paragraph id where it appears
- **THEN** a text fact is registered with the parsed value, its unit and the paragraph id, and can be used in derived facts

#### Scenario: Quote not in paragraph
- **WHEN** an agent quotes a number string that does not appear in the cited paragraph
- **THEN** the quote is refused and no fact is registered

### Requirement: Derived facts from closed operations
New figures SHALL be produced only by a fixed set of operations (percent change, ratio, share of a total, sum, difference) applied to fact ids in the registry. Each result SHALL be added to the registry with its operation and inputs. An operation on an unknown id or an undefined result (such as a zero divisor) SHALL return an error to the agent, not a value.

#### Scenario: Derive a share
- **WHEN** the storyteller asks for a segment's share of total revenue using two registered fact ids
- **THEN** a new fact is registered with the result, the operation and both input ids, and its id is returned

#### Scenario: Zero divisor
- **WHEN** a ratio is requested with a divisor fact whose value is zero
- **THEN** the operation returns an error and no fact is registered

### Requirement: Low-confidence caveats
A citation of a low-confidence fact SHALL carry a caveat, and the displayed story SHALL mark it. A `tension` finding SHALL NOT rest on low-confidence facts alone.

#### Scenario: Caveat missing
- **WHEN** the story cites a low-confidence free-cash-flow fact without a caveat
- **THEN** verification rejects the story

#### Scenario: Tension on weak data
- **WHEN** every fact cited by a `tension` finding has low confidence
- **THEN** verification rejects the story

### Requirement: Citations to report paragraphs
Every claim drawn from report text SHALL cite paragraph ids from the reports covered by the story. Each cited id SHALL exist in that fiscal year's report, and the displayed citation SHALL link to its page in the original document.

#### Scenario: Unknown paragraph
- **WHEN** the story cites a paragraph id that is not in the cited fiscal year's report
- **THEN** verification rejects the story

#### Scenario: Page link
- **WHEN** a cited paragraph is displayed
- **THEN** its link opens the source document at that paragraph's page

### Requirement: Changes explained only where text changed
The what-changed section SHALL be based only on business-description sections that the report comparison classified as changed, new or dropped. Sections classified as unchanged SHALL NOT be sent to an LLM, and the story SHALL list them as unchanged.

#### Scenario: Unchanged section skipped
- **WHEN** the customers section has the same text in all three reports
- **THEN** no LLM call receives it, and the story lists it as unchanged

### Requirement: Verification before saving
A story SHALL be verified before it is saved or returned. A rejected story SHALL get exactly one repair attempt, with the verification errors sent to the storyteller. If the repaired story still fails, the run SHALL fail with the list of errors and nothing SHALL be saved as the latest story.

#### Scenario: Repaired story
- **WHEN** the first story has one unknown fact token and the repaired story passes
- **THEN** the repaired story is saved, and the run records both attempts

#### Scenario: Repair fails
- **WHEN** both attempts fail verification
- **THEN** the run fails with the verification errors, and the previously saved story stays the latest

### Requirement: Token budget
Before any LLM call, a story run SHALL estimate the input tokens of the report text it will send. A run whose estimate exceeds the configured story budget SHALL be refused with an error that gives the estimate and the budget.

#### Scenario: Over budget
- **WHEN** the estimated input exceeds the configured story budget
- **THEN** the run is refused before any LLM call, with the estimate and the budget in the error

### Requirement: Saved story runs
Each successful run SHALL be saved with its `as_of`, the fiscal years and filing ids covered, the fact registry, every agent's output, the verification result, the models used, hashes of the prompts and configuration, and its token usage and cost. The latest saved run for a company SHALL be retrievable without any LLM or provider call.

#### Scenario: Read saved story
- **WHEN** the latest story for Malam is requested in cached mode after a successful run
- **THEN** the saved run is returned unchanged, at no cost

#### Scenario: No saved story
- **WHEN** the latest story is requested for a company with no saved run
- **THEN** the request fails with a "not cached" error

### Requirement: Renders from saved facts
A saved story SHALL render its numbers from the fact registry saved with it, not from current data, so it reads the same after the provider revises a value.

#### Scenario: Provider revision
- **WHEN** a provider value cited by a saved story is later revised
- **THEN** the saved story still shows the value it was written with

### Requirement: Progress events
A live story run SHALL report its progress as a sequence of events: the reports selected, each agent started and finished, each tool call, verification, and a final event carrying the saved run or the error.

#### Scenario: Progress order
- **WHEN** a live story run succeeds
- **THEN** events report report selection, then agent and tool activity, then verification, and the last event carries the saved run

### Requirement: Story from the CLI
The CLI SHALL show the latest saved story for a ticker, and in live mode SHALL generate a new one, printing progress and the rendered story.

#### Scenario: CLI live run
- **WHEN** the story command runs for MLTM in live mode
- **THEN** progress lines are printed, followed by the three rendered sections with fact values and page citations
