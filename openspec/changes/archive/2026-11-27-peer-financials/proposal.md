# Proposal

## Why

Analysts can fetch one company's financial statements, but must choose comparable issuers by hand. A domestic market with a single listed operator makes the choice especially important because a foreign operator can provide a financial benchmark while facing different regulation and competitors.

## What Changes

- Select listed issuers from the provider directory in Israel (`IL`) by default, using the target's exact business classification, with reproducible results.
- Preserve an empty or short domestic result. Let the caller explicitly name foreign markets to fill remaining places with labelled international analogues.
- Add a CLI runner that fetches annual financial statements for selected issuers and a testing agent that checks both request behavior and the business relevance of matches.

## Capabilities

### New Capabilities

- `peer-financials` covers peer selection, annual statement retrieval, and offline evaluation of the result.

### Modified Capabilities

## Impact

The server gains company profile and directory reads through its existing FinancialReports client, a peer selection service, a Typer command, and pytest coverage. Directory reads and annual financial requests use the existing cache and live access controls.
