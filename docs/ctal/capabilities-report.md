# CTAL: description and capabilities report

Scope: state of the working tree after the "bring everything online" round (see git log); previously `da295e5` on branch `ccr-fd981673-pt8zx2` (PR #39, draft). CI was green on the previous commit (Python 3.9 and 3.12). Local: 92 tests OK (Python 3.13.16, Node 22.22.0). Status words: PROVEN, UNVERIFIED, BLOCKED, UNTESTED, SPECIFIED.

## 1. Description
CTAL (Continuous Trust and Assurance Ledger) is a gate placed in front of a protected action, for example releasing content. For each request it runs two **separate** checks:
- **AQPD**: is the content acceptable? (adversarial-quality assessment)
- **CLES**: is the caller entitled? (signed, scoped, time-bounded, revocable license)

It releases the action only when AQPD says `ACCEPT` and CLES says `AUTHORIZED`. Every decision is recorded as a signed, versioned **assurance envelope** in a per-customer, tamper-evident ledger. A customer can export a signed evidence package and verify it offline with an independent program, with no database access and no production secrets.

Not a content-truth oracle: a valid signature proves integrity and attribution only.

## 2. Components
| Component | Path | What it does |
|---|---|---|
| Canonicalization | `ctal/canon.py` | `ctal-cjson-1` (RFC 8785 subset): sorted keys, no floats, NFC strings, duplicate/oversize/deep input rejected |
| Keys and trust | `ctal/keys.py` | Ed25519 (maintained `cryptography` library); algorithm fixed by config; key purpose and status (active, retired, revoked) |
| Contracts | `ctal/contracts.py` | AQPD, CLES and outcome vocabularies; fail-closed decision matrix |
| AQPD | `ctal/aqpd.py`, `ctal/adapters/js/AQPD.js` | Contract, a reference engine, and your supplied JS engine |
| CLES | `ctal/cles.py`, `ctal/adapters/js/CLES.js` | Contract, a reference verifier, and your supplied JS engine |
| Node bridge | `ctal/adapters/` | Runs the JS engines in a killable subprocess; maps their codes to CTAL statuses |
| Envelope | `ctal/envelope.py` | Build, sign, verify; recomputes the decision from the separate AQPD and CLES statuses |
| Ledger | `ctal/store.py` | SQLite; tenant-bound access; per-tenant hash chain; immutable policies, envelopes and checkpoints; idempotency; reversible migration; backup |
| Orchestrator | `ctal/gate.py` | Fail-closed, idempotent, self-verifying; key rotation and revocation |
| Export | `ctal/export.py` | Signed zip: events, envelopes, policies, signed checkpoint, public keys, manifest |
| Offline verifier | `ctal/verifier/ctal_verify.py` | Standalone; pinned trust root; reports what was and was not established |
| HTTP API | `ctal/server.py` | Bearer-key auth, roles (gate, auditor, admin), body and concurrency limits |
| Operations | `ctal/config.py`, `ctal/__main__.py` | Environment config; refuses development keys in production; CLI `demo`, `serve`, `migrate`, `create-api-key`, `export-pubkey` |
| Hygiene | `ctal/tools/scan_secrets.py`, `.github/workflows/ctal.yml` | Secret-pattern scan; CI on Python 3.9 and 3.12 with Node 22 |

## 3. Decision behavior (default)
| AQPD | CLES | Outcome |
|---|---|---|
| ACCEPT | AUTHORIZED | PROCEED |
| WARN, REVIEW, UNKNOWN | AUTHORIZED | HOLD_FOR_REVIEW |
| QUARANTINE, REJECT | any | BLOCK |
| ERROR | any | ERROR |
| any | DENIED, EXPIRED, REVOKED, INVALID_SIGNATURE, UNKNOWN | BLOCK |
| any | ERROR | ERROR |
| missing or invalid status | any | ERROR |

Proceeding on WARN is possible only through an explicit, versioned decision policy that is bound into the signed policy digest. Tested exhaustively over all 49 combinations: only (ACCEPT, AUTHORIZED) proceeds by default.

## 4. Capabilities and evidence
| Capability | Status | Evidence |
|---|---|---|
| Separate AQPD and CLES with typed statuses and reason codes | PROVEN | `test_aqpd`, `test_cles`, `test_js_adapters` |
| Fail-closed orchestration (timeout, exception, invalid or wrong-policy result, signing failure) | PROVEN | `test_gate` |
| Envelope signature covers every field; any change, addition, removal or algorithm/key swap fails | PROVEN | `test_envelope` |
| Tenant isolation across API read, write, search, export; body-claimed tenant rejected | PROVEN (no background workers exist) | `test_ledger`, `test_server` |
| Idempotent retry; concurrent duplicates yield one protected action | PROVEN (single-node SQLite) | `test_gate` |
| Tamper evidence: edit, delete, reorder, substitute, truncate | PROVEN within the model | `test_ledger`, `test_export` |
| Offline verification with a pinned key; no private key or database | PROVEN locally | `test_export`, `python3 -m ctal demo` |
| Immutable versioned policies; old decisions stay tied to their version | PROVEN | `test_ledger` |
| Key rotation, revocation; production refuses `dev-` keys | PROVEN | `test_server`, `test_hygiene` |
| Migration rollback; SQLite backup/restore with intact chain | PROVEN | `test_ledger` |
| Supplied AQPD.js / CLES.js end to end; signature format defined in `crypto.js` and independently reproduced in Python | PROVEN | `test_js_adapters` (16 tests) |
| **License activation limits** (`maxActivations`) enforced per license and instance | PROVEN | `test_online`, `test_js_adapters` |
| **Live, permanent, per-tenant license revocation** (admin API) | PROVEN | `test_online` |
| **Incident-to-regression**: reviewer proposes, a *different* admin approves, content frozen, replay against any policy version catches regressions | PROVEN | `test_online.RegressionFlow` |
| **Metrics** from the ledger: decisions, rates, gate latency p50/p95, regression counts | PROVEN (ledger-derivable metrics only) | `test_online` |
| **License-expiry reminders** (query of licenses expiring within N days) | PROVEN as a query; nothing sends notifications | `test_online` |
| **Signed release manifest + SBOM**, linked to the envelope release digest | PROVEN (source-tree manifest, not a build attestation) | `test_online.ReleaseProvenance` |
| **TLS 1.2+**, per-key and per-address **rate limiting**, **W3C traceparent** correlation, production refuses to serve without TLS | PROVEN locally | `test_online.Transport` |
| Python 3.9 and 3.12 | PROVEN in CI for the previous commit; re-check on the PR for this one | PR checks |

## 5. Limits (what it does not do)
- **Chain alone does not stop a database admin** who rewrites history and recomputes every hash (a test demonstrates this). Customers must keep earlier signed exports.
- The export key is the offline trust root. Whoever holds it can sign a complete forged export.
- **Supplied JS engines:** that they are the production versions is UNVERIFIED. AQPD's four regex rules are easy to evade; detection accuracy is UNTESTED and no accuracy claim is made. AQPD.js never emits WARN or QUARANTINE.
- **Not built:** KMS/HSM signing (BLOCKED: no key vault available; keys are 0600 PEM files). PostgreSQL backend with row-level security (a PostgreSQL 16 server exists in the sandbox but is stopped; porting the storage layer is a separate piece of work; today one SQLite file holds all tenants). Notification delivery for expiring licenses. OpenTelemetry exporter (trace ids are propagated and logged). Retention and deletion procedure. Cross-customer intelligence (deferred by design).
- External side effects are at-least-once; only the internal protected-action record is exactly-once.
- Metrics that need customer data (coverage, manual review time, false positive/negative rates) cannot be computed by CTAL.
- Regression cases store reviewer-supplied sample content (at most 64 KiB) so they can be replayed.
- **Not deployed:** local demonstration only. Python 3.11 UNTESTED locally (broken system package).

## 6. Commercial status
No buyer, budget owner, recurring cost or pilot has been validated. Candidate workflow: a content-release gate. Validation checklist: `docs/ctal/pilot-runbook.md`. No market, compliance, tamper-proof or accuracy claim is made.

## 7. How to run
```bash
pip install -r ctal/requirements.txt
python3 -m unittest discover -s ctal/tests -t .     # 92 tests (Node required for the JS adapter tests)
python3 -m ctal demo                                 # gate, ledger, signed export, offline verify, tamper check
CTAL_ENV=development python3 -m ctal serve --port 8080
```
Further docs: `docs/ctal/README.md` (index), `evidence-matrix.md`, `risk-register.md`, `architecture-and-threat-model.md`, `operations.md`, `js-integration.md`.
