# Spec Delta

## ADDED Requirements

### Requirement: Track a company from search
For each provider search result that is not tracked, the client SHALL offer an action to add it. The action SHALL open a form with the ticker and Hebrew name prefilled from the result and editable, and SHALL require both before submitting. After a successful add, the tracked-companies list and the search result SHALL show the company as tracked without a page reload.

#### Scenario: Add from search
- **GIVEN** the client is in live mode
- **WHEN** the user searches, chooses "add to tracking" on an untracked result, and submits the form
- **THEN** the company appears in the tracked-companies list, and the search result links to it instead of showing "not tracked"

#### Scenario: Provider gives no ticker
- **WHEN** the user opens the add form for a result without a ticker
- **THEN** the ticker field is empty and the form cannot be submitted until a ticker is entered

#### Scenario: Add refused
- **WHEN** the server refuses the add, for example because the ticker is already tracked
- **THEN** the form stays open and shows the API's error message

### Requirement: Stop tracking an added company
The client SHALL offer a "stop tracking" action only on companies whose source is `added`, SHALL ask for confirmation, and after a successful removal SHALL drop the company from the tracked-companies list without a page reload.

#### Scenario: Remove an added company
- **GIVEN** the client is in live mode and ABC was added at runtime
- **WHEN** the user chooses "stop tracking" on ABC and confirms
- **THEN** ABC disappears from the tracked-companies list

#### Scenario: Version-controlled company
- **WHEN** the tracked-companies list shows MLTM
- **THEN** no "stop tracking" action is offered for it

### Requirement: Tracking actions need live mode
In cached mode, the client SHALL show the add and stop-tracking actions as disabled, with an explanation that they need live mode. When the server is cached-only, that explanation SHALL say that live mode is turned off on the server.

#### Scenario: Cached mode
- **WHEN** the client is in cached mode and shows an untracked search result
- **THEN** its add action is disabled and explains that live mode is needed
