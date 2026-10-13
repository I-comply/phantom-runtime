# Operations

## Setup
```bash
pip install -r ctal/requirements.txt
export CTAL_ENV=production CTAL_DB=/var/lib/ctal/ctal.db
export CTAL_ENVELOPE_KEY=/etc/ctal/envelope.pem  CTAL_ENVELOPE_KEY_ID=prod-envelope-2026-01
export CTAL_EXPORT_KEY=/etc/ctal/export.pem      CTAL_EXPORT_KEY_ID=prod-export-2026-01
export CTAL_ISSUER_TRUST=/etc/ctal/issuers.json  CTAL_REVOKED_LICENSES=/etc/ctal/revoked.json
python3 -m ctal migrate up
python3 -m ctal create-api-key <tenant> admin <label>     # printed once; stored hashed
python3 -m ctal serve --host 127.0.0.1 --port 8080        # put TLS + rate limiting in front
```
Production refuses: missing key files (no auto-generate), key ids starting `dev-`, key files readable by group/other. Generate production keys outside the repo with a maintained tool (e.g. `openssl genpkey -algorithm ed25519 -out envelope.pem`; `chmod 600`) or, preferably, a KMS/HSM (not integrated: BLOCKED).

## Health
`/healthz` (process), `/readyz` (schema migrated). Request logs are one JSON line without bodies or tokens.

## Key rotation (envelope key)
1. Generate new key file; start with new id. 2. In-process today: `gate.rotate_envelope_key(new_signer, ledgers, actor)` marks the old key `retired` (still verifies) and records `key_rotated` per tenant. 3. Distribute the new export public key / trust file to verifiers. 4. After the overlap period nothing else is needed; retired keys remain in exports so old envelopes verify.
Rotation of the **export** key: customers must re-pin; keep the old public key to verify old exports.
Entitlement issuer keys: add the new key to `CTAL_ISSUER_TRUST` (overlap), later mark old `retired`/`revoked`.

## Suspected key compromise
`gate.revoke_key(key_id, ledgers, actor, reason)` → status `revoked`; all envelopes signed by that key fail verification (strict model; re-issue by re-assessment). Rotate, notify customers to re-pin, review events since the suspected time, preserve the DB and prior exports as evidence.

## Backup / restore
Backup: `Store.backup_to(dest)` (SQLite online backup API, consistent while serving). Restore: stop service, copy backup over `CTAL_DB`, start, call `TenantLedger.verify_chain()` per tenant (tested). Back up key files separately and encrypted. Restore drill not performed on production-like infrastructure (UNTESTED).

## Migration rollback
`python3 -m ctal migrate down --version 0001_init` drops all CTAL tables (destructive: take a backup first). Migrations are additive and versioned in `ctal/migrations/`.

## Incident response (first hour)
1. Contain: revoke affected API keys (`Store.revoke_api_key`), revoke suspect signing keys. 2. Preserve: copy DB + WAL, prior exports. 3. Verify: `verify_chain()` for each tenant; run the offline verifier on the latest export and compare against the last export held by the customer. 4. Scope: query events by time range / correlation id. 5. Communicate; document in the ledger via `remediation_created` (event type reserved; not automated).

## Retention / deletion
Raw content is never stored; only SHA-256 digests, statuses, reason codes, and tenant metadata. Deletion of a tenant's records would break hash chains and prior exports' consistency; a documented tombstone/legal-hold procedure is SPECIFIED, not implemented.
