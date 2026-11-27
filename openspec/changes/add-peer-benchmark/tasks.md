## 1. Verify data (before coding)
- [x] 1.1 Read MLTM's profile `sub_industry` (code and label) and the cached IL/US/EU directory pages from `kv_cache`. Record whether Accenture, Capgemini and Sopra Steria share the class, and report the credits needed to fill any gap. Done: nothing for MLTM's profile or directory is stored. Accenture plc (ID 29813) is in ISIC 6220. The old Accenture Ltd is delisted and in 8299.
- [x] 1.2 Confirm the D1 matching choice with the user (a curated list, falling back to exact sub-industry).
- [x] 1.3 Resolve provider IDs for MLTM's curated peers (Accenture, Capgemini, Sopra Steria) from stored search results, or with announced metadata calls (1 credit each). Done for Accenture (3 search credits + 40 for financials). Capgemini and Sopra Steria are left (about 82 credits).

## 2. Server
- [x] 2.1 Ratios by provider company ID (split `analyze`), with tests
- [x] 2.2 Curated `peers` field on tracked companies (companies.yaml), and per-market cohorts from the curated list or the exact-class fallback (D1, D2) in `services/peer_benchmark.py`, leaving the CLI spec unchanged; tests
- [x] 2.3 `services/peer_benchmark.py`: per-peer ratios, template and not-cached statuses, medians with n; tests
- [x] 2.4 GET (cached only) and POST (estimate, confirm, capped fetch) endpoints, schemas and OpenAPI regeneration; API tests
- [x] 2.5 `stock-analyzer peer-benchmark` CLI wrapper

## 3. Web
- [x] 3.1 Regenerate `schema.d.ts`; add `features/peers/PeerBenchmarkPage.tsx`, its route, and a tab next to Ratios
- [x] 3.2 Live-run button with credit estimate and confirmation

## 4. Verify
- [x] 4.1 Server tests (`PYTHONUTF8=1`) and web typecheck and tests pass (web vitest not run: node_modules lacks vitest)
- [ ] 4.2 The MLTM tab renders against stored peers in the browser preview
