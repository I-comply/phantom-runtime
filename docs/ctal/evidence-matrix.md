# Evidence matrix

"Tests passed" = run in this environment (Python 3.13.16): `python3 -W error::ResourceWarning -m unittest discover -s ctal/tests -t .` → **92 tests, OK** (16 exercise the supplied AQPD.js/CLES.js through a Node bridge; Node v22.22.0); also OK on Python 3.12 (64 run + 1 skipped because `jsonschema` not installed in that interpreter). Python 3.9/3.11: UNTESTED (3.9 absent; 3.11's system `cryptography` package is broken, environmental). Syntax-only parse for 3.9 passed.

Scope caveat: AT-01..06 are proven twice: against the **reference** engines written in this change (`test_aqpd.py`, `test_cles.py`) and against the **supplied AQPD.js/CLES.js** (`test_js_adapters.py`). The JS runs use `crypto.js` as defined in this repo (original unavailable, nothing issued before; format cross-checked independently in Python). That the JS files are the production versions is unverified. See js-integration.md for 8 findings and their mitigations.

| Req | Implementation (new code) | Tests | Status |
|---|---|---|---|
| AQPD contract, statuses, reason codes, bounded resources | `ctal/aqpd.py`, `ctal/gate.py` (timeout/exception/invalid-result → `ERROR`) | `test_aqpd.py`, `test_gate.py` | PROVEN (contract + reference engine). Supplied AQPD.js: PROVEN via bridge (rules fixed; accuracy UNTESTED) |
| AT-01 benign | reference engine | `test_aqpd.test_at01_benign` | PROVEN (reference) |
| AT-02 adversarial | pattern rules; no accuracy claim | `test_at02_adversarial_and_warn` | PROVEN (reference); detection accuracy UNTESTED/no claim |
| AT-03 malformed/oversized/nested/duplicate/timeout | `canon.parse_strict`, size caps, gate timeout | `test_at03_bounds_and_malformed`, `test_canon`, `test_gate.test_aqpd_timeout_is_typed_error` | PROVEN. Caveat: a timed-out Python thread cannot be killed (see risk R-06) |
| CLES contract (signature, tenant/product, window, expiry, revocation, key id/rotation) | `ctal/cles.py`, `ctal/keys.py` | `test_cles.py` | PROVEN (reference). Supplied CLES.js: PROVEN via bridge |
| AT-04 valid entitlement | | `test_at04_valid` | PROVEN (reference) |
| AT-05 tamper / unknown key / wrong-purpose key / token-chosen algorithm | | `test_at05_*`, `test_algorithm_chosen_by_token_is_rejected`, `test_wrong_purpose_key_cannot_authorize` | PROVEN |
| AT-06 expired, not-yet-valid, revoked, wrong tenant/product, malformed, invalid sig | | `test_at06_lifecycle_negatives`, `test_reason_codes_for_scope`, `test_revoked_issuer_key_and_rotation` | PROVEN. Revocation source is a static list; live feed **BLOCKED** (no service) |
| Canonicalization `ctal-cjson-1` | `ctal/canon.py` | `test_canon.py`, `test_export.test_independent_canonicalization_matches_service` | PROVEN (RFC 8785 subset: no floats; NFC strings; documented) |
| Versioned signed envelope | `ctal/envelope.py`, `schemas/assurance-envelope.v1.schema.json` | `test_envelope.py` | PROVEN |
| AT-07 any signed-field change fails | | `test_at07_every_field_change_fails` (every leaf field mutated; added/removed fields; sig swap) | PROVEN |
| AT-08 decision separation | `ctal/contracts.py`, `ctal/gate.py` | `test_at08_matrix_exhaustive` (49 combos + invalid inputs), `test_gate.*` | PROVEN: only (ACCEPT, AUTHORIZED) proceeds by default; WARN→PROCEED only via explicit versioned decision policy |
| AT-09 tenant isolation | `ctal/store.py:TenantLedger`, `ctal/server.py` | `test_ledger.test_at09_*`, `test_server.test_at09_cross_tenant_read_write_search_export`, `test_gate.test_tenant_mismatch_*` | PROVEN for API + store. No background workers exist in this P0 (N/A) |
| Ledger: tenant-scoped trace/search, hash chain, signed checkpoints | `ctal/store.py`, `ctal/export.py` | `test_ledger.py` | PROVEN (see limits in threat model) |
| AT-10 signed export verifies offline | `ctal/export.py`, `ctal/verifier/ctal_verify.py` | `test_export.test_at10_*` (separate process, `python -I`, no private keys) | PROVEN locally |
| AT-11 altered/deleted/reordered/substituted material | | `test_export.test_at11_deeper_tampering_with_resigned_manifest` (12 attacks), `test_untouched_manifest_*`, `test_ledger.test_at11_*` | PROVEN within model. `test_known_limit_*` PROVES the documented gap: a full recomputed rewrite is undetectable by the chain alone |
| AT-12 retry/idempotency/replay | `store.claim`, `gate.process` | `test_gate.test_at12_*`, `test_envelope.test_replay_freshness_option` | PROVEN on single-node SQLite. Downstream external side effects: at-least-once only (**SPECIFIED**) |
| AT-13 policy immutability + pinned decisions | `store.publish_policy`, triggers | `test_ledger.test_at13_*` | PROVEN. "Approved regression replays against policy versions": **SPECIFIED** (Phase 7, P1, not implemented) |
| AT-14 secret hygiene | `ctal/tools/scan_secrets.py` | `test_hygiene.py` | PROVEN with own pattern scanner only; gitleaks/trufflehog not run (UNTESTED) |
| AT-14 migration rollback | `migrations/0001_init.{up,down}.sql` | `test_ledger.test_at14_migration_rollback_and_reapply` | PROVEN (SQLite) |
| AT-14 backup/restore | `Store.backup_to` | `test_ledger.test_at14_backup_restore_preserves_chain` | PROVEN (SQLite file); PostgreSQL path UNTESTED |
| Key lifecycle (rotate/revoke, no unknown keys, prod refuses dev keys) | `gate.rotate_envelope_key/revoke_key`, `config.py` | `test_server.test_key_rotation_and_revocation_lifecycle`, `test_hygiene.test_production_*` | PROVEN. KMS/HSM integration: **BLOCKED** (no KMS available; PEM file boundary only) |
| One runnable workflow | `ctal/server.py`, `ctal/demo.py` ("content-release gate") | `python3 -m ctal demo` (exit 0); `test_server.py` | PROVEN as local demonstration. **Not deployed** |
| CI | `.github/workflows/ctal.yml` | not yet executed on GitHub at time of writing | UNTESTED (see PR checks) |
| Observability | structured request logs (no bodies/tokens) with trace id, `/healthz`, `/readyz`, `/v1/metrics`, `/v1/metrics/summary` | `test_server.py`, `test_online.py` | PROVEN basic; OTLP exporter not implemented (SPECIFIED) |
| Activation limits (`maxActivations`) | `store.register_activation`, `gate._ledger_entitlement_checks` | `test_online.ActivationAndRevocation`, `test_js_adapters.test_gate_enforces_*` | PROVEN |
| Live, permanent, tenant-scoped license revocation (admin API) | `store.revoke_license`, `POST /v1/revocations` | `test_online.test_live_revocation_*` | PROVEN. Issuer-side external feed: none exists |
| P1 Incident→regression with human approval (two-person rule), frozen content, replay against policy versions | `store.propose_case/decide_case`, `/v1/incidents`, `/v1/regressions*` | `test_online.RegressionFlow` | PROVEN. Stores reviewer-supplied sample content (≤64 KiB) by design; list API returns digests only |
| P1 Release provenance + SBOM | `ctal/release.py`, CLI `release-manifest` / `release-verify` | `test_online.ReleaseProvenance` | PROVEN as signed source-tree manifest + CycloneDX subset; NOT a hermetic build attestation (SLSA) |
| P1 Value metrics (decisions, rates, p50/p95 gate latency, regression counts) | `ctal/metrics.py`, `/v1/metrics/summary` | `test_online.MetricsAndReminders` | PROVEN for ledger-derivable metrics; coverage, review time, accuracy NOT computable here |
| P1 License expiry reminders | `metrics.expiring_licenses`, `/v1/licenses/expiring` | `test_online.MetricsAndReminders` | PROVEN as a query; no notification delivery (no mail/webhook channel configured) |
| TLS (≥1.2), per-key and per-address rate limiting, W3C `traceparent` correlation | `server.py`, CLI flags | `test_online.Transport` | PROVEN locally; production serve refuses to run without TLS or `--behind-tls-proxy` |
| P2: cross-customer intelligence | — | — | Deferred; disabled (no code) |
| Commercial validation (buyer, budget owner, recurring cost) | — | — | **UNTESTED**: no buyer conversations performed |
