# peer-financials Specification

## Purpose

Find listed issuers with comparable business activities and retrieve their annual statements, including in markets with few listed peers.

## Requirements

### Requirement: Domestic peer selection

The runner SHALL resolve the tracked target's provider ID, match listed issuers in Israel (`countries=IL`) with the target's exact ISIC sub-industry, exclude the target, deduplicate across pages by issuer ID, and select up to the requested positive limit in ascending numeric provider ID order.

#### Scenario: Default market is Israel

- **WHEN** the analyst omits foreign countries and the target has a known sub-industry
- **THEN** the runner searches only Israel, including when the target's provider country is missing or differs from IL

#### Scenario: Repeated or reordered candidates

- **WHEN** a domestic search for issuer 40 returns matching IDs 70, 40, 15, 15 and 10 across pages with limit two
- **THEN** the selected IDs in order are 10 and 15 regardless of page boundaries or directory order

### Requirement: Domestic coverage

The result SHALL record the domestic search outcome and eligible count after exclusions. A completed search with zero or few matches SHALL describe provider coverage without inferring monopoly status or expanding geography or classification implicitly.

#### Scenario: Sole listed operator in the covered class

- **WHEN** the directory returns only the target and the caller requested domestic peers
- **THEN** the run succeeds with domestic count zero, an empty peer list, reason `no_domestic_matches`, and zero financial requests

#### Scenario: Too few domestic peers

- **WHEN** the limit is five and two eligible issuers are found in the domestic directory
- **THEN** a domestic-only run returns the two issuers and domestic count two

#### Scenario: Unknown classification

- **WHEN** the target profile lacks its sub-industry
- **THEN** the result identifies the missing metadata, leaves the domestic count unknown and makes zero candidate and financial requests

#### Scenario: Incomplete directory search

- **WHEN** the second required domestic page is unavailable in cached mode or fails in live mode
- **THEN** the runner reports the underlying error and issues zero financial requests

### Requirement: Explicit international analogues

When the caller supplies foreign country codes, the runner SHALL fill remaining places with listed issuers in those countries using the same exact sub-industry. Domestic peers SHALL come first, followed by unique foreign issuers ordered by numeric provider ID. Each issuer SHALL carry its country and domestic or international designation.

#### Scenario: Benchmarking a sole domestic operator abroad

- **WHEN** the domestic count is zero and the caller requests foreign markets with a limit of two
- **THEN** the result retains the zero domestic count and its reason and returns at most two international analogues from the requested markets

#### Scenario: Domestic peers fill every place

- **WHEN** there are enough domestic matches to satisfy the limit
- **THEN** the runner fills all places domestically and makes zero international directory requests

### Requirement: Peer statements

The CLI SHALL emit JSON containing selection context and the selected issuers' identities and annual statements using the existing financial grouping, reporting currencies, fiscal years, decimal strings and missing values. The financial request set SHALL include only selected issuer IDs. The run SHALL respect the requested cache or live mode.

#### Scenario: Untracked issuers in different currencies

- **WHEN** two selected peers outside the registry report in different currencies
- **THEN** each issuer's output carries its own currency and annual values, the registry is unchanged, and the run requests no filings, report text or target financials

### Requirement: Offline peer evaluation

The testing agent SHALL run the runner against fixed provider data and report selected IDs against independently reviewed target-specific judgements. It SHALL distinguish accepted, unsuitable, and unreviewed selections, identify missed expected issuers, and display reviewed business reasons.

#### Scenario: Operationally distinct foreign issuer

- **WHEN** an international analogue shares a class with the target but a reviewer records a materially different business model
- **THEN** its selection passes the classification rule and the evaluation flags the unsuitable issuer with the reviewer's reason

#### Scenario: Expected empty peer set

- **WHEN** a benchmark expects zero domestic peers and the runner returns zero
- **THEN** the agent records the expected empty result as a pass without calculating a percentage from an empty set
