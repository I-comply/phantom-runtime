# Architecture, data flow and threat model

## Data flow (content-release gate)
```
client --Bearer key + Idempotency-Key--> POST /v1/gate
  auth -> tenant (from key)      role check            claim idempotency (new|replay|conflict|in_progress)
  policy = latest immutable version in tenant registry
  AQPD adapter  (timeout, exceptions -> ERROR)  --> AqpdResult   } separate results,
  CLES adapter  (token, tenant, product)         --> ClesResult   } never merged into a score
  decide(AQPD, CLES) -> PROCEED | BLOCK | HOLD_FOR_REVIEW | ERROR   (fail closed; only ACCEPT+AUTHORIZED proceeds)
  build envelope -> canonicalize (ctal-cjson-1) -> Ed25519 sign -> self-verify (fail closed on failure)
  one DB transaction: envelope + 5 ledger events (+ protected action iff PROCEED) + idempotency complete
GET /v1/export -> events/envelopes/policies/checkpoint(signed)/trust keys/manifest(signed) zip
ctal_verify.py (offline, pinned export key) -> report: checked / not_established
```

## Trust model
- Algorithm (Ed25519) and canonicalization id are fixed by configuration/code; values in untrusted input are only compared, never selected.
- Keys carry a purpose (`envelope`, `entitlement`, `export`) and status (`active`, `retired` verify-only, `revoked` never valid). Unknown key ids are never trusted.
- Offline trust root = the **export public key pinned out-of-band**. Envelope public keys inside the archive are trusted only because the pinned key signed the manifest digesting them; an additional envelope-key pin is optional.
- A valid signature proves integrity and attribution under these keys. It does **not** prove that content is true, safe, lawful, or that AQPD/CLES decided correctly.

## Integrity model (what is and is not detected)
| Attack | Detected? |
|---|---|
| Edit/delete/reorder/substitute an event in DB without fixing hashes | Yes (`verify_chain`, verifier) |
| Same, with all hashes recomputed, by someone with DB write access | Chain alone: **No** (test `test_known_limit_*`). Yes if a prior signed checkpoint/export is compared |
| Edit exported files | Yes (manifest digests, manifest signature) |
| Edit exported files and re-sign manifest without the export key | Yes |
| Tail truncation of the exported event list | Yes (signed checkpoint head) |
| Events omitted from the export by the operator before checkpoint signing | No |
| Operator holding the export signing key forges a complete export | No — mitigated only by key custody and pinning |
| Cross-tenant event/envelope inserted into a tenant export | Yes (tenant check) |

## Tenant isolation
Tenant is derived server-side from the API key. `TenantLedger` is constructed from an authenticated context and every statement includes `tenant_id`. A tenant claimed in the request body is rejected (403) and recorded as `envelope_verification_failed` in the *authenticated* tenant's ledger only. Entitlement tokens carry their own tenant and are denied on mismatch.

## Not covered
TLS (terminate in front), network policy, DDoS, host hardening, KMS/HSM custody, PostgreSQL RLS, legal retention/deletion, regulatory compliance (no control set mapped).
