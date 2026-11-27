# Design

## Context

The CLI already calls the peer and market research services. The web client has typed company requests, cached/live controls, a financials table, and an OSINT flow that reads saved results and starts fresh research on demand.

## Goals / Non-Goals

Expose both existing services through typed company routes and make their results usable from the tracked company page. Cross-company comparisons use reported fiscal-year amounts in their native units.

## Decisions

1. Add company-scoped peer financials and market research routes. Reuse the request context and mode guard. Peer GET accepts the existing scope and mode options. Market GET uses cached service behavior for every valid read. Market POST takes the market set and window and requires live mode.
2. Follow the company's OSINT streaming approach for market POST. Give the client a pending state while research runs and deliver a typed result or error. Prevent overlapping runs for the same normalized ticker, market set, and window within a server process. Release the slot on success or failure.
3. Add two company routes to the Hebrew RTL app. The peer view combines peer results with a separate cached request to the existing target financials endpoint. Align statement keys and line-item codes for a selected fiscal year, using the latest available year by default. Start with income, balance sheet, and cash flow groups. Preserve decimal strings and currencies. The target fetch never goes live as a side effect of peer discovery.
4. The market view defaults to Israel, Europe, and the US and lets the user choose a subset and window. Preserve per-market findings, citations, source geography and comparison limits. Key client queries by normalized scope and update the matching cached result after a live run.
5. Generate client types from the updated API schema. Reuse existing navigation, request, loading, empty, and error components.

## Risks / Trade-offs

- Mixed currency and sparse year coverage affect comparisons. Show the currency with each issuer and display unavailable cells explicitly.
- Provider-backed calls can incur charges. Use cached requests on entry and gate live actions on user intent and existing mode settings.
- Market research may outlast a browser request. Use the existing stream lifecycle and expose the saved result through GET after completion.
