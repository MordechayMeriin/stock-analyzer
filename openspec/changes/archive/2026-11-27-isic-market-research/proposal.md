# Proposal

## Why

Company OSINT assesses one issuer's stability. An analyst also needs a view of demand, competition, and regulation across the industry that issuer operates in.

## What Changes

- Add a market research CLI that accepts a tracked ticker and resolves the issuer's ISIC Rev. 5 class using the same provider profile lookup as peer search.
- Cover Israel, Europe, and the United States by default. Use the existing OSINT search and citation checks to produce a brief with evidence and coverage gaps for each market.
- Test the production ticker lookup and allow fixed class metadata in offline tests.

## Capabilities

### New Capabilities

- `market-research` covers ticker-scoped industry research and evidence reporting.

### Modified Capabilities

## Impact

The CLI gains a market research command. The new service uses the tracked registry, FinancialFilings company metadata, and shared OSINT search and citation infrastructure.
