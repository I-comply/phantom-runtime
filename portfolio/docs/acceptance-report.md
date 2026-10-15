# Acceptance report — 2026-10-15

State vocabulary: **VERIFIED** (checked against primary evidence), **IMPLEMENTED** (code exists), **TESTED** (automated test passes), **DEPLOYED** (running in a hosted environment), **NOT VERIFIED**.

## Result
Build complete for the accessible scope. **Not ready for production publication**: ownership/AI-authorship review, owner publication approval, deployment authorization and inquiry-notification path are open (see "Stop conditions").

## Evidence
| Area | State | Evidence |
|---|---|---|
| Source access manifest | VERIFIED | `private/docs/source-access-manifest.md`; 23 repositories listed by the integration, all cloned read-only; handoff leads not found are recorded as such |
| Repository inventory with provenance | IMPLEMENTED, VERIFIED | `scripts/inventory/inventory.py` → `private/inventory/sources-inventory.json` (commit SHA, LOC, tests, licenses, secret-pattern findings per repo) |
| Asset register (25 records, stable IDs, dispositions) | IMPLEMENTED, TESTED | 7 PURSUE, 6 INTEGRATE, 7 REFERENCE, 5 ARCHIVE; `npm run validate`; schema tests |
| Ownership / license status | VERIFIED as *unresolved* | `private/docs/IP-and-rights-review.md`; no exclusivity claimed |
| Market comparables | NOT VERIFIED | Direct fetch of acquire.com / flippa.com failed; no realized-sale comparable obtained; sample size 0 everywhere |
| Pricing | IMPLEMENTED (provisional, LOW) | Replacement-cost model v1.0.0 (`scripts/lib/valuation.mjs`); every assumption in each record and memo |
| Storefront (home, catalog, asset pages, how-it-works, about, inquiry, privacy) | IMPLEMENTED, TESTED | `tests/site.test.mjs` |
| Per-asset packages for 7 PURSUE assets | IMPLEMENTED, TESTED | page, 10–12 slide pitch deck (+PDF, +md), 5–7 slide deck with speaker notes (+PDF, +md), demo page, private diligence package (11 files each + SBOM) |
| Demos | TESTED | Recorded real runs on synthetic data (`RECORDED_RUN`), transcripts checked for expected strings; not hosted, not interactive |
| Public/private separation | TESTED | whitelist projection, canary test, built-site leak scan, 404 for `/private/*` |
| Contact | VERIFIED | Only `drs.vault@proton.me` is shown; phone number stored but not published (tested) |
| Inquiry flow | TESTED locally | 201 stored / 422 / honeypot / 415 / 400 / 413 / 429; durable owner-only file; **no email delivery** |
| Accessibility & responsive | TESTED (static checks) + visually spot-checked | lang, landmarks, labels, skip link, focus, reduced motion, light/dark; screenshots reviewed at desktop and 500 px width. No automated axe/Lighthouse run; no real-device test |
| Security | TESTED (controls) | CSP without inline scripts, traversal/dotfile blocks, rate limits; no pen test |
| CI | IMPLEMENTED | `.github/workflows/portfolio.yml` — **not yet run on GitHub** |
| Deployment | NOT DEPLOYED | Dockerfile not built (no Docker daemon); deployment/rollback guides written; smoke script run against a local server (17/17 ok) |
| Private diligence area (authenticated) | NOT IMPLEMENTED | intentionally; see architecture.md |
| Analytics | IMPLEMENTED (first-party anonymous counters), TESTED | no third-party analytics |

## Test runs (2026-10-15)
| Suite | Result |
|---|---|
| Portfolio `node --test` | 30 / 30 pass (3 consecutive runs) |
| CTAL (`pytest ctal`) | 92 passed |
| phantomkit `verify.sh` | 110 fixture checks passed, 0 failed; self-scan 0 findings |
| replaycheck | 21 tests OK |
| temporal-kernel | 19 tests OK |
| Agent Trust Layer | 21 tests: 7 passed, 14 skipped (Docker / py_ecc unavailable) |
| governance-gateway | 15 passed |
| iComply (vitest) | 30 passed, 1 skipped (needs Postgres) |
| phantom-runtime-main backend | not run locally (needs Postgres); GitHub Actions run 38816613498 succeeded on main |

## Definition-of-done checklist
- [x] Source access manifest lists accessible, partial, missing, denied sources.
- [x] Inventory with provenance.
- [x] Asset register with IDs, maturity, disposition, dependencies, blockers.
- [x] Ownership/license status documented without unsupported claims.
- [x] Every PURSUE asset has page, pitch deck, short deck, demo, pricing memo, diligence index.
- [ ] Every realized-sale benchmark cites a verified source — **none exists**; prices are labelled provisional instead.
- [x] Recommended prices state methodology, sample size (0), confidence (LOW), rights, assumptions, exclusions.
- [x] Public pages and demos contain no secrets or confidential data (tested).
- [x] Contact details verified or omitted.
- [x] Public/private separation tested.
- [x] All buttons, links, inquiry flow and downloads work locally (link test, smoke test, server tests). Inquiry notification to the owner is not implemented.
- [x] Tests and build pass (failures/limits listed above).
- [~] Accessibility/responsive/security/dependency/secret scans documented — see limits above; full-history secret and dependency/license audits of the marketed assets are open.
- [x] Deployment and rollback instructions written; tested locally only.
- [x] No external publication, paid spend, ownership change or production deployment occurred.

## Stop conditions (production publication blocked until resolved)
1. Counsel review of ownership and AI-assisted authorship.
2. Owner approval (`publication.approved`) per asset.
3. Deployment authorization and a tested inquiry-notification path.
4. Full-history secret scan and dependency/license audit for each marketed asset.
5. Realized-sale comparables (needs network access to the marketplaces) to replace provisional prices.

## Reproduce
```bash
cd portfolio
npm run register && npm run validate && npm test && npm run build:staging && node scripts/build-diligence.mjs
PORT=8099 node src/server.mjs & BASE=http://127.0.0.1:8099 bash scripts/smoke.sh
```
