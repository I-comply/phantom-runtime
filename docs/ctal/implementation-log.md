# Implementation log

| # | Action | Command / paths | Result |
|---|---|---|---|
| 1 | Read spec bundle | CLAUDE_CODE_EXECUTION_PROMPT.md, CTAL_Claude_Code_Handoff.{md,json}, bundle zip | No conflict between MD and JSON found |
| 2 | Inventory + search for AQPD/CLES | `grep -rIil`, `git grep` (last 50 commits), clone+grep `I-comply/agent-trust-layer` | Not found → reference adapters + BLOCKED live integration |
| 3 | Baseline | `temporal-kernel/verify.sh`, `replaycheck/verify.sh` | 19 + 21 tests OK |
| 4 | Contracts/foundations | `ctal/canon.py keys.py contracts.py timeutil.py` | Ed25519 via `cryptography`; no custom crypto |
| 5 | AQPD/CLES | `ctal/aqpd.py cles.py` | contract + reference implementations (separate modules, separate tests) |
| 6 | Envelope | `ctal/envelope.py schemas/` | signed over canonical unsigned envelope; decision recomputed on verify |
| 7 | Ledger/policies/migrations | `ctal/store.py migrations/` | SQLite, tenant-bound, hash chain, immutable triggers, reversible migration |
| 8 | Orchestration | `ctal/gate.py` | fail closed, idempotent, self-verifying |
| 9 | Export + verifier | `ctal/export.py verifier/ctal_verify.py` | independent module, pinned trust root |
| 10 | API + CLI + demo | `ctal/server.py config.py __main__.py demo.py` | |
| 11 | Tests | `ctal/tests/*` | 65 tests |
| 13 | Supplied `AQPD_CLES_Two_Implementations.zip` integrated | `ctal/adapters/*`, `tests/test_js_adapters.py`, `docs/ctal/js-integration.md` | 79 tests OK; originals byte-identical; crypto.js reconstructed |
| 12 | CI, docs | `.github/workflows/ctal.yml`, `docs/ctal/*` | CI not yet run on GitHub when written |

## Final local runs (Python 3.13.16)
```
python3 -W error::ResourceWarning -m unittest discover -s ctal/tests -t .   -> Ran 65 tests ... OK
python3 -m ctal demo                                                        -> exit 0; verifier exit 0 on export, exit 1 on tampered export
python3 ctal/tools/scan_secrets.py ctal docs/ctal                          -> 0 finding(s)
python3.12 -m unittest discover -s ctal/tests -t .                          -> OK (skipped=1: jsonschema not installed there)
python3.11 -m unittest ...                                                  -> import error from broken system cryptography package (environmental); UNTESTED
```

## Defects found by tests during development (fixed)
- Gate accepted an AQPD result object with an invalid status string and only failed at envelope self-verification; now validated at the adapter boundary (still fail closed either way).
- Several test-side mistakes (non-deterministic envelope ordering in a tamper test, wrong expected counts, an illegal reorder statement) corrected; no assertion was weakened.

## Design decisions
- SQLite for P0: zero-dependency, transactional, trigger support. PostgreSQL/RLS is the scale-up path (UNTESTED).
- Strict revocation: a revoked signing key invalidates previously signed envelopes (no trustworthy signing-time source).
- `WARN` holds for review by default; proceeding on WARN requires an explicit versioned decision policy bound into `policy_bundle_digest`.
- Subject content is never stored; digest computed server-side, never taken from the caller.
- Release digest = sha256 of source tree (or `CTAL_RELEASE_DIGEST`); it is not a build attestation.

## Known limitations
Reference AQPD/CLES only; no KMS/HSM; no TLS; no rate limiting; single-node SQLite; static revocation list; no P1 features; no OpenTelemetry exporter; no buyer validation; CI unexecuted at time of writing.
