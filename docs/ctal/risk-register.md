# Risk register

| ID | Risk | Likelihood / Impact | Mitigation in place | Residual / action |
|---|---|---|---|---|
| R-01 | Reference engines mistaken for production; supplied JS engines depend on a reconstructed `crypto.js` | High / High | Reference code labelled; JS files kept byte-identical; reconstruction flagged in file header and docs | Obtain original `crypto.js` and issued-license fixtures; confirm provenance. Open |
| R-12 | CLES.js gaps | Med / Med | Bridge enforces required scope; gate enforces maxActivations and live revocations from the ledger | No external issuer revocation feed. Mitigated |
| R-02 | Signing key compromise (envelope or export) | Med / High | Keys outside repo, 0600 PEM, prod refuses `dev-*`; rotation + revocation + ledger events; revoked key invalidates old envelopes (strict) | No KMS/HSM yet (BLOCKED). Compromise of export key lets an attacker forge a whole export; mitigate by pinning key out-of-band and rotating |
| R-03 | Privileged DB admin rewrites history incl. hashes | Low–Med / High | Triggers (naive edits), hash chain, signed checkpoint in each export | Proven undetectable by chain alone (test). Customers must retain earlier exports/checkpoints; consider external anchoring only if a buyer requires it |
| R-04 | Tenant isolation bug | Low / Critical | Tenant derived from API key; every SQL has `tenant_id=?`; negative tests across API/store/export | SQLite has no RLS; one DB file for all tenants. For stronger isolation use per-tenant DBs or PostgreSQL RLS (UNTESTED) |
| R-05 | Canonicalization ambiguity | Low / High | Strict subset: no floats, NFC, no duplicates, depth/size caps, shared vectors with verifier | Not full RFC 8785 (numbers); documented |
| R-06 | AQPD timeout leaves a running thread | Med / Low | Result `ERROR`; JS engines run in a killable subprocess (hard timeout) | Only the in-process reference engine can leave a thread. Reduced |
| R-07 | Idempotent replay vs. crash after external effect | Med / Med | Protected action recorded in same transaction as envelope; stale in-progress claim lease 60 s | External webhooks are at-least-once; pass the idempotency key downstream |
| R-08 | API keys are bearer secrets | Med / Med | Hashed at rest, revocable, roles, rate limiting (per key / per address), concurrency cap (32), body cap 1 MiB, TLS ≥1.2 supported, production refuses to serve without TLS or declared proxy | Key rotation policy and WAF/DDoS protection are deployment concerns. Reduced |
| R-09 | Retention/deletion conflicts with immutable log | Med / Med | Raw content not stored (digest only) | Retention policy/deletion procedure SPECIFIED, not implemented |
| R-10 | Market not validated | High / High | Pilot runbook + checklist | No buyer evidence exists; do not claim demand |
| R-11 | Multi-interpreter coverage | Low / Low | CI matrix 3.9 & 3.12 (green) | 3.11 UNTESTED |
| R-13 | Regression cases store sample content | Low / Med | ≤64 KiB, explicit reviewer action, two-person approval, listing returns digests only | Define retention/deletion (SPECIFIED) |
| R-14 | SQLite single file for all tenants | Med / Med | Tenant-bound access layer, tested | PostgreSQL + RLS backend NOT built (a PostgreSQL 16 cluster exists in the sandbox but is stopped; porting `store.py` is a separate piece of work) |
