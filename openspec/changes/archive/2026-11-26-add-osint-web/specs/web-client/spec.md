## MODIFIED Requirements

### Requirement: OSINT stability view
The client SHALL offer, from the company page, the latest stored OSINT result for a chosen window: overall
label, rationale and Hebrew summary, the six areas with Hebrew names, labels and assessments, risks, strengths,
and numbered sources with link, date, area, signal and confidence. Cited finding numbers SHALL link to their
sources. The view SHALL show run metadata and dropped-finding counts, and state it uses open sources only.

#### Scenario: Stored scorecard
- **WHEN** the user opens the OSINT view of ELAL, which has a stored 36-month result
- **THEN** the scorecard, six areas, risks, strengths, summary and numbered sources are shown, marked as a stored result

#### Scenario: Cited source reachable
- **WHEN** the user follows a finding number cited by a risk
- **THEN** the page moves to that numbered source, which is not hidden under the page header

#### Scenario: Another window
- **WHEN** the user chooses a 12-month window
- **THEN** the view shows the stored 12-month result, or says none has been run for that window

#### Scenario: Never researched
- **WHEN** the user opens the OSINT view of a company with no stored result for the window
- **THEN** an empty state says no research has been run for that window

#### Scenario: Run only in live mode
- **WHEN** the client is in cached mode or the server is cached-only
- **THEN** no action to run research is shown and the view explains why; in live mode the run action is offered

## ADDED Requirements

### Requirement: Filing-derived and undated findings marked
In the OSINT view, a finding whose source restates figures from the company's official reports SHALL be
visibly marked as filing-derived, and a finding with no publish date SHALL be visibly marked as undated.

#### Scenario: Marks shown
- **WHEN** the sources include a filing-derived finding and an undated finding
- **THEN** the first carries a filing-derived mark and the second an undated mark, and other findings carry
  neither

### Requirement: Live OSINT run from the client
In live mode the OSINT view SHALL offer to run fresh research for the chosen window, starting only after the
user confirms a warning that a run searches afresh, takes minutes and costs about $1 of OpenRouter credit.
While it runs the view SHALL show progress and keep the previous result; it SHALL then show the new result, or
the error. In cached mode the action SHALL NOT be offered, and the view SHALL say live mode is needed.

#### Scenario: Confirmed live run
- **WHEN** the user in live mode chooses to run research and confirms the cost warning
- **THEN** progress is shown while it runs, and the new result replaces the old one when it is done

#### Scenario: Cancelled before start
- **WHEN** the user dismisses the cost warning
- **THEN** no run is started
