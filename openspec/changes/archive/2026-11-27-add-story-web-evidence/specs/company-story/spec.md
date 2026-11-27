# Spec Delta

## ADDED Requirements

### Requirement: Web evidence for the storyteller only
The storyteller SHALL be able to read the company's stored OSINT findings, run live web searches and quote numbers from web sources. The agents that read report text (describe, change and explain) SHALL NOT have web tools, and their outputs SHALL rest on report text only.

#### Scenario: Reader agents stay report-only
- **WHEN** a story run starts its describe, change and explain agents
- **THEN** none of them can search the web or read OSINT findings

#### Scenario: Storyteller reads findings
- **WHEN** the storyteller asks for the stored OSINT findings of the credit area
- **THEN** it receives the kept credit findings with their claim, source, publish date and source id

### Requirement: OSINT research started when missing or stale
Before the storyteller runs, a live story run SHALL use the company's stored OSINT result for the default window. When no result is stored, or the stored result is older than the configured maximum age (default 30 days, measured from today), the run SHALL start a normal OSINT research run alongside the report readers and SHALL wait for it before the storyteller starts.

#### Scenario: Fresh stored result
- **WHEN** a story run starts and the stored OSINT result for the company is 10 days old
- **THEN** the stored result is used and no OSINT research run is started

#### Scenario: No stored result
- **WHEN** a story run starts and no OSINT result is stored for the company
- **THEN** an OSINT research run is started, its result is stored as the latest OSINT result, and the storyteller receives its findings

#### Scenario: Stale stored result
- **WHEN** a story run starts and the stored OSINT result is 45 days old
- **THEN** a new OSINT research run is started and replaces the stored result

#### Scenario: Readers do not wait
- **WHEN** an OSINT research run is started by a story run
- **THEN** the describe, change and explain agents run at the same time as the research run

### Requirement: OSINT research dated today
An OSINT research run started by a story SHALL be an ordinary run dated today, whatever the story's `as_of`. The story SHALL filter its findings by `as_of` and SHALL NOT store a research result dated as of a past day.

#### Scenario: Story with a past as_of
- **WHEN** a story with an `as_of` a year ago starts an OSINT research run
- **THEN** the research run and its stored result are dated today, and only findings dated on or before `as_of` reach the storyteller

### Requirement: OSINT failure does not fail the story
When an OSINT research run started by a story fails or keeps no findings, the story run SHALL continue without stored findings, SHALL keep its live web search tool, and SHALL record a warning in the saved run.

#### Scenario: Research finds nothing
- **WHEN** the OSINT research run started by a story ends with no usable findings
- **THEN** the story run continues, the storyteller can still search the web, and the saved run has a warning about the research run

### Requirement: OSINT research already running
A live story run that needs an OSINT research run SHALL be refused before any LLM call when an OSINT research run for the same company and window is already in progress.

#### Scenario: Research in progress
- **WHEN** a story run needs an OSINT research run while one for the same company is running from the research page
- **THEN** the story run is refused with an error saying research is in progress, and no LLM call is made

### Requirement: Live web search during a story
The storyteller SHALL be able to search the web. Every search SHALL exclude the OSINT block-list of official filing sources, SHALL discard any blocked result before the storyteller sees it, and SHALL record each returned source in the run, with its URL, title, excerpt and publish date when known. A search result's publish date SHALL come only from a date that code finds in its title or excerpt; the LLM SHALL NOT supply it.

#### Scenario: Date found in the excerpt
- **WHEN** a search result's excerpt begins "פורסם 12.03.2026"
- **THEN** the source is recorded with the publish date 2026-03-12

#### Scenario: No date in the excerpt
- **WHEN** neither the title nor the excerpt of a search result contains a date
- **THEN** the source is recorded as undated

#### Scenario: Blocked result
- **WHEN** a storyteller search returns a result on a block-listed filing domain
- **THEN** the result is discarded and cannot be cited

#### Scenario: Search usage logged
- **WHEN** the storyteller runs a search that is not cached
- **THEN** a usage record with a story-search purpose, tokens, cost and latency is appended to the usage log

### Requirement: Story search limit
A story run SHALL allow at most the configured number of storyteller searches (default 20), counted across the first storyteller attempt and its repair. The storyteller SHALL be told the limit, and every search result SHALL report the searches left. A request for a search beyond the limit SHALL fail the story run, and nothing SHALL be saved.

#### Scenario: Searches left reported
- **WHEN** the storyteller runs its fifth search with a limit of 20
- **THEN** the search result reports 15 searches left

#### Scenario: Limit exceeded
- **WHEN** the storyteller asks for a 21st search with a limit of 20
- **THEN** no search is made, the story run fails with an error listing the searches already run, and the previously saved story stays the latest

#### Scenario: Limit shared with the repair
- **WHEN** the first storyteller attempt used 15 searches and verification asks for a repair
- **THEN** the repair attempt has 5 searches left

### Requirement: Story searches cached by query and as_of
A storyteller search SHALL be cached by its query, its result settings and the story's `as_of`. A repeated search with the same query and `as_of` SHALL return the cached results at no cost. A search for a different `as_of` SHALL search the web afresh.

#### Scenario: Rerun on the same as_of
- **WHEN** a story run for Malam is repeated with the same `as_of`, inputs and configuration
- **THEN** every storyteller search and model turn is served from the cache at zero cost

#### Scenario: New as_of
- **WHEN** a story run uses a query that an earlier run used with a different `as_of`
- **THEN** the search goes to the web and its results are cached under the new `as_of`

### Requirement: Web sources limited to as_of
No web source dated after the story's `as_of` SHALL reach the storyteller or be cited by the story. Stored OSINT findings dated after `as_of` SHALL be removed before the storyteller starts, and search results dated after `as_of` SHALL be discarded. When `as_of` is before today, undated stored findings and undated search results SHALL also be removed.

#### Scenario: Undated result for a past as_of
- **WHEN** a story with an `as_of` a year ago receives an undated search result
- **THEN** the result is discarded before the storyteller sees it

#### Scenario: Undated result for today
- **WHEN** a story with `as_of` today receives an undated search result
- **THEN** the storyteller sees it and can cite it as additional evidence, but not as the only basis of a paragraph

#### Scenario: Later stored finding removed
- **WHEN** a stored OSINT finding is dated after the story's `as_of`
- **THEN** the storyteller does not receive it

#### Scenario: Later source cited
- **WHEN** the story cites a web source dated after `as_of`
- **THEN** verification rejects the story

### Requirement: Numbers quoted from web sources
A number from a web source SHALL enter the registry only by quoting it from that source's excerpt. Code SHALL check that the quoted text appears in the excerpt and SHALL parse its value, scale and currency. A quote not found in the excerpt, a quote checked only against a search summary, or a money amount without a detectable currency SHALL be refused.

#### Scenario: Quote from a live result
- **WHEN** the storyteller quotes "200 מיליון ש"ח" from the excerpt of a search result in this run
- **THEN** a web fact is registered with the value 200,000,000, currency ILS and the source id

#### Scenario: Quote from a stored finding
- **WHEN** the storyteller quotes a number that appears in the stored excerpt of an OSINT finding
- **THEN** a web fact is registered citing that finding

#### Scenario: Number only in the summary
- **WHEN** the storyteller quotes a number that appears in a search summary but not in any excerpt
- **THEN** the quote is refused and no fact is registered

#### Scenario: Foreign currency
- **WHEN** the storyteller quotes "$50 million" from an excerpt
- **THEN** the fact is registered in USD and is displayed in dollars, not shekels

#### Scenario: Stored finding without an excerpt
- **WHEN** the storyteller quotes a number from a stored finding saved before excerpts were kept
- **THEN** the quote is refused with an error saying the source has no excerpt

### Requirement: Web numbers are low confidence
Every fact quoted from a web source SHALL have low confidence. Its caveat SHALL say that the number comes from a press source and is not audited.

#### Scenario: Web number without a caveat
- **WHEN** a story paragraph cites a web fact without listing it as a caveat
- **THEN** verification rejects the story

#### Scenario: Tension on web numbers
- **WHEN** every fact a `tension` finding cites is a web fact
- **THEN** verification rejects the story

### Requirement: Citations to web sources
Story paragraphs and findings SHALL be able to cite web sources by source id, next to report paragraph ids. Every cited source id SHALL be a stored OSINT finding given to this run or a source returned by a search in this run. The displayed citation SHALL show the source's title and publish date and SHALL link to its URL.

#### Scenario: Unknown source
- **WHEN** the story cites a source id that no stored finding or search in the run provided
- **THEN** verification rejects the story

#### Scenario: Web citation shown
- **WHEN** a story paragraph cites a web source
- **THEN** the displayed citation shows the source title and publish date and links to its URL

### Requirement: Web-only paragraphs for post-report events
A what-changed paragraph that cites no report paragraph SHALL cite only web sources dated after the latest covered report's publication date and on or before `as_of`. Every other story paragraph SHALL cite at least one report paragraph. A source with no known publish date SHALL NOT be the only basis of a paragraph.

#### Scenario: Post-report event
- **WHEN** a what-changed paragraph about a CEO change cites only a news source dated after the FY2025 report was published and before `as_of`
- **THEN** verification accepts the paragraph

#### Scenario: Event before the report
- **WHEN** a what-changed paragraph cites only a web source dated before the latest report's publication
- **THEN** verification rejects the story

#### Scenario: Undated source alone
- **WHEN** a what-changed paragraph cites only a web source with no publish date
- **THEN** verification rejects the story

#### Scenario: What the company does
- **WHEN** a what-it-does paragraph cites only web sources
- **THEN** verification rejects the story

### Requirement: No circular corroboration
A web source marked as restating the company's own filings SHALL NOT be the only web source supporting a story paragraph or finding.

#### Scenario: Filing-derived article alone
- **WHEN** a what-changed paragraph cites only a news article marked as derived from a filing
- **THEN** verification rejects the story

#### Scenario: Filing-derived article with another source
- **WHEN** a finding cites a filing-derived article together with a report paragraph and an independent news source
- **THEN** verification accepts the citation

## MODIFIED Requirements

### Requirement: Story sections
A story SHALL contain three sections in Hebrew: what the company does (from the latest report), what changed across the three fiscal years and after the latest report up to `as_of`, and how the story fits the numbers.

#### Scenario: Complete story
- **WHEN** a story run succeeds
- **THEN** it contains the three sections, each with at least one paragraph of Hebrew text

#### Scenario: Event after the latest report
- **WHEN** the company's rating was cut after its latest report was published and before `as_of`
- **THEN** the what-changed section can describe the cut, citing the web source that reported it

### Requirement: Story-versus-numbers findings
The story-versus-numbers section SHALL be a list of findings. Each finding SHALL be labelled `consistent`, `tension` or `unexplained`, and SHALL cite at least one fact and at least one report paragraph. Web sources cited by a finding SHALL count only as additional evidence.

#### Scenario: Labelled finding
- **WHEN** management attributes revenue growth to a segment, and that segment's share of revenue fell
- **THEN** the finding is labelled `tension` and cites the revenue facts and the directors'-report paragraph making the claim

#### Scenario: Finding without a fact
- **WHEN** a finding cites only report paragraphs and no fact
- **THEN** verification rejects the story

#### Scenario: Finding with only web sources
- **WHEN** a finding cites a fact and web sources but no report paragraph
- **THEN** verification rejects the story

#### Scenario: Outside explanation
- **WHEN** management does not explain a fall in revenue and a news source reports a lost tender
- **THEN** the finding stays `unexplained`, cites the revenue facts and a report paragraph, and cites the news source as additional evidence

### Requirement: Fact registry
Each story run SHALL keep a registry of the facts available to it: normalized financial values, year-over-year changes, core ratios, numbers quoted from report text, numbers quoted from web sources, and derived values. Each fact SHALL have a stable id, an exact decimal value or none, a unit, the fiscal years it covers, its input fact ids, and its confidence with any failed check ids.

#### Scenario: Change fact
- **WHEN** the registry is built for Malam FY2023 to FY2025
- **THEN** it contains a revenue change fact for FY2024 to FY2025 whose inputs are the two revenue values

#### Scenario: Web fact
- **WHEN** a number is quoted from a web source
- **THEN** the registry holds a web fact with its value, unit, currency, source id and the quoted text

### Requirement: Changes explained only where text changed
The what-changed section SHALL draw on report text only from business-description sections that the report comparison classified as changed, new or dropped. Sections classified as unchanged SHALL NOT be sent to an LLM, and the story SHALL list them as unchanged. Events after the latest report's publication SHALL be described only from web sources.

#### Scenario: Unchanged section skipped
- **WHEN** the customers section has the same text in all three reports
- **THEN** no LLM call receives it, and the story lists it as unchanged

### Requirement: Token budget
Before any LLM call, a story run SHALL estimate the input tokens of the report text it will send plus the most its storyteller searches can return. A run whose estimate exceeds the configured story budget SHALL be refused with an error that gives the estimate and the budget.

#### Scenario: Over budget
- **WHEN** the estimated input exceeds the configured story budget
- **THEN** the run is refused before any LLM call, with the estimate and the budget in the error

#### Scenario: Searches counted
- **WHEN** the search limit or the results per search are raised
- **THEN** the estimate grows by the extra search results the storyteller could receive

### Requirement: Saved story runs
Each successful run SHALL be saved with its `as_of`, the fiscal years and filing ids covered, the fact registry, every agent's output, the web sources it was given or found, the OSINT result it used, its searches, the verification result, the models used, hashes of the prompts and configuration, and its token usage and cost. The latest saved run for a company SHALL be retrievable without any LLM or provider call.

#### Scenario: Read saved story
- **WHEN** the latest story for Malam is requested in cached mode after a successful run
- **THEN** the saved run is returned unchanged, at no cost

#### Scenario: No saved story
- **WHEN** the latest story is requested for a company with no saved run
- **THEN** the request fails with a "not cached" error

#### Scenario: Web sources saved
- **WHEN** a saved story cites a web source
- **THEN** the saved run holds that source's URL, title, publish date and excerpt, so the story renders the same after the stored OSINT result is replaced

### Requirement: Progress events
A live story run SHALL report its progress as a sequence of events: the reports selected, whether stored OSINT findings are used or a research run is started, each agent started and finished, each research area finished, each tool call including each web search with the searches left, verification, and a final event carrying the saved run or the error.

#### Scenario: Progress order
- **WHEN** a live story run succeeds
- **THEN** events report report selection, then agent and tool activity, then verification, and the last event carries the saved run

#### Scenario: Research progress
- **WHEN** a story run starts an OSINT research run
- **THEN** events report that the research run started, each area as it finishes, and when the research result is stored
