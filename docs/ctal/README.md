# CTAL: Continuous Trust and Assurance Ledger (P0)

Implementation of directive CH-CTAL-001 in `ctal/`. Status vocabulary: PROVEN, FAILED, BLOCKED, UNTESTED, SPECIFIED.

**AQPD / CLES:** neither was in this repository (searched this repo, the last 50 commits, and `I-comply/agent-trust-layer`). CTAL defines the contracts (`ctal/aqpd.py`, `ctal/cles.py`) and ships labelled *reference* engines. The user later supplied `AQPD.js` and `CLES.js`; they are integrated through a Node bridge ([js-integration.md](js-integration.md), `CTAL_ENGINE=js`). Their dependency `crypto.js` does not exist anywhere (no copy, no licenses issued before), so `ctal/adapters/js/crypto.js` now defines the signature format and is cross-checked by an independent Python implementation. Provenance of the files as "the production code" is unverified.

| Doc | Content |
|---|---|
| [repository-inventory.md](repository-inventory.md) | What was found, baseline results |
| [evidence-matrix.md](evidence-matrix.md) | Requirement → file → test → status |
| [risk-register.md](risk-register.md) | Risks and mitigations |
| [architecture-and-threat-model.md](architecture-and-threat-model.md) | Data flow, trust model, what a privileged operator can still do |
| [operations.md](operations.md) | Setup, config, key rotation, backup/restore, rollback, incident response |
| [pilot-runbook.md](pilot-runbook.md) | Workflow, metric definitions, buyer-validation checklist |
| [capabilities-report.md](capabilities-report.md) | Description and capabilities report |
| [js-integration.md](js-integration.md) | Supplied AQPD.js/CLES.js: mapping, findings, gaps |
| [implementation-log.md](implementation-log.md) | Commands, outputs, decisions, limitations |

## Quick start (local demonstration, development keys)

```bash
pip install -r ctal/requirements.txt
python3 -m unittest discover -s ctal/tests -t .      # 92 tests
python3 -m ctal demo                                  # gate -> ledger -> signed export -> offline verify -> tamper check
```

Run the service: `CTAL_ENV=development CTAL_DB=ctal.db python3 -m ctal serve --port 8080`, then `python3 -m ctal create-api-key <tenant> <gate|auditor|admin> <label>`.

Offline verification (no database, no private keys, separate process, imports nothing from `ctal`):

```bash
python3 -m ctal export-pubkey                         # prints: <export_key_id> <base64url public key>; pin out-of-band
python3 ctal/verifier/ctal_verify.py export.zip --pin-export-key-id=ID --pin-export-public-key=PUB
```

## Remaining AQPD / CLES unblock steps (original `crypto.js`; see js-integration.md)
Historic generic steps, still valid for any other engine:
1. Provide the repository (or package) that contains AQPD and CLES.
2. AQPD: implement `ctal.aqpd.AqpdEngine.assess(content, media_type, policy) -> AqpdResult` (statuses `ACCEPT|WARN|QUARANTINE|REJECT|REVIEW|UNKNOWN|ERROR`) as a thin adapter; pass it to `Gate(...)`.
3. CLES: implement `verify(token, tenant_id, product_id) -> ClesResult` and a `RevocationSource`; map the real token format/issuer keys into `TrustStore` entries with purpose `entitlement`. If CLES uses HMAC or another algorithm, add it as an explicit, config-fixed algorithm; do not accept an algorithm from the token.
4. Re-run `ctal/tests` plus adapter-specific suites; update the evidence matrix.
