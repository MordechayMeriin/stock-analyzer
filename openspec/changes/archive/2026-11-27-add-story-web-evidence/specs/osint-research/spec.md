# Spec Delta

## MODIFIED Requirements

### Requirement: Cited findings
Each finding SHALL carry a claim, an area, a signal (positive, negative or neutral), a confidence (high,
medium or low), a source URL and the source's publish date when known. Each kept finding SHALL also carry
the source excerpt that the web search returned for its URL, and the stored result SHALL keep it. A
finding whose search returned no excerpt SHALL be kept without one.

#### Scenario: Finding fields
- **WHEN** a specialist reports a finding
- **THEN** the finding has a claim, area, signal, confidence and source URL

#### Scenario: Excerpt kept
- **WHEN** a finding is kept and its URL was returned by a search with an excerpt
- **THEN** the kept finding and the stored result carry that excerpt, as the search returned it

#### Scenario: Result stored before excerpts
- **WHEN** a stored result saved before excerpts were kept is read
- **THEN** it loads, and its findings have no excerpt
