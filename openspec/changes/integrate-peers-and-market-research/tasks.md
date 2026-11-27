# Tasks

## 1. Company API

- [ ] 1.1 Add the peer GET route using the existing peer service. Test cached and explicit live requests, option validation, zero peers, exact decimals, and CLI parity.
- [ ] 1.2 Add market GET and streamed live POST. Test cache-only reads, successful stream completion, typed errors, same-scope concurrency, and prevention of provider calls when live is refused.
- [ ] 1.3 Regenerate OpenAPI and TypeScript client types, add typed client methods, and verify both schema freshness checks.

## 2. Company web views

- [ ] 2.1 Add peer comparison navigation, scope controls, year selection, and an aligned table. Verify native currencies, missing target data, empty domestic results, and explicit live fetches.
- [ ] 2.2 Add market research navigation, market and time controls, the stored brief, and the live run flow. Verify citations, regional coverage, evidence gaps, and cache updates after a live run.
- [ ] 2.3 Exercise both company routes in a browser test. Assert cached reads on navigation, no paid calls before explicit user action, and the existing OSINT page remains reachable.
