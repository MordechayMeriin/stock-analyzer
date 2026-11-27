# Proposal

## Why

Peer discovery and industry research are available on the command line. Analysts using the company page need access to both features alongside the existing financial statements and company OSINT scorecard.

## What Changes

- Expose ticker-based peer financials and industry market research through the company API.
- Add a peer comparison view and a cited market brief view to the company page.
- Use cached reads on page load and explicit user actions for paid live requests.

## Capabilities

### New Capabilities

### Modified Capabilities

- `analyzer-api` gains company peer financials and market research endpoints.
- `web-client` gains peer comparison and industry market research views.

## Impact

FastAPI routers, generated OpenAPI and client types, company navigation, and API and browser tests. The endpoints call the existing research and peer selection services.
