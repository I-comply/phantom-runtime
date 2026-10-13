# CTAL: description and capabilities report

Scope: state at commit `da295e5` on branch `ccr-fd981673-pt8zx2` (PR #39, draft). CI green on that commit (Python 3.9 and 3.12). Local: 80 tests OK (Python 3.13.16, Node 22.22.0). Status words: PROVEN, UNVERIFIED, BLOCKED, UNTESTED, SPECIFIED.

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
| Tenant isolation across API read, write, search and export; body-claimed tenant rejected | PROVEN (store, API, export; no background workers exist) | `test_ledger`, `test_server` |
| Idempotent retry; concurrent duplicates yield one protected action | PROVEN (single-node SQLite) | `test_gate` |
| Tamper evidence: edit, delete, reorder, substitute, truncate | PROVEN within the model | `test_ledger`, `test_export` (12 re-signed-manifest attacks) |
| Offline verification with a pinned key; no private key or database | PROVEN locally | `test_export`, `python3 -m ctal demo` |
| Immutable, versioned policies; old decisions stay tied to the version used | PROVEN | `test_ledger` |
| Key rotation (overlap), revocation, production refuses `dev-` keys | PROVEN | `test_server`, `test_hygiene` |
| Migration rollback; SQLite backup and restore with intact chain | PROVEN | `test_ledger` |
| Supplied AQPD.js / CLES.js run through CTAL end to end | PROVEN | `test_js_adapters` (14 tests) |
| Request limits, structured logs without bodies or tokens, health and readiness, admin metrics | PROVEN (basic) | `test_server` |
| Python 3.9 and 3.12 | PROVEN in CI | PR checks |

## 5. Limits (what it does not do)
- **Chain alone does not stop a database admin** who rewrites history and recomputes every hash (a test demonstrates this). Customers must keep earlier signed exports.
- The export key is the offline trust root. Whoever holds it can sign a complete forged export.
- **Supplied JS engines:** `crypto.js` was missing; a labelled reconstruction is used, so compatibility with already-issued licenses is UNVERIFIED. That the files are the production versions is UNVERIFIED. `CLES.maxActivations` is not enforced. Revocations are a static list with no live feed. AQPD's 4 regex rules are easy to evade; detection accuracy is UNTESTED and no accuracy claim is made.
- AQPD.js never emits WARN or QUARANTINE.
- Signing keys are PEM files; KMS/HSM is BLOCKED (none available). No TLS, rate limiting, or PostgreSQL row-level security. One SQLite file holds all tenants.
- External side effects are at-least-once; only the internal protected-action record is exactly-once.
- Not implemented: incident-to-regression and replay (P1), release attestations or SBOM (release digest is a source-tree hash), value-metric collection, OpenTelemetry export, retention and deletion procedure, cross-customer intelligence (deferred, no code).
- Not deployed: local demonstration only. Python 3.11 UNTESTED locally (broken system package).

## 6. Commercial status
No buyer, budget owner, recurring cost or pilot has been validated. Candidate workflow: a content-release gate. Validation checklist: `docs/ctal/pilot-runbook.md`. No market, compliance, tamper-proof or accuracy claim is made.

## 7. How to run
```bash
pip install -r ctal/requirements.txt
python3 -m unittest discover -s ctal/tests -t .     # 80 tests (Node required for the JS adapter tests)
python3 -m ctal demo                                 # gate, ledger, signed export, offline verify, tamper check
CTAL_ENV=development python3 -m ctal serve --port 8080
```
Further docs: `docs/ctal/README.md` (index), `evidence-matrix.md`, `risk-register.md`, `architecture-and-threat-model.md`, `operations.md`, `js-integration.md`.
