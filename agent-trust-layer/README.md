# Agent Trust Layer (ATL)

Vertical slice: identity -> capability policy -> authorization (+ approver) -> sandboxed execution -> tenant-scoped hash-chained ledger -> evidence -> external anchor -> offline verifier. Python 3.9+, stdlib only.

    ./verify.sh                       # tests + demo
    python3 -m atl init
    python3 -m atl principal issue acme my-agent          # prints secret once
    python3 -m atl principal issue acme alice --kind approver
    python3 -m atl serve                                  # POST /v1/invoke
    python3 -m atl verify acme [--chain-only]             # exit 1 on tamper
    python3 -m atl anchor acme                            # ATL_ANCHOR_WEBHOOK optional
    python3 -m atl mcp                                    # stdio MCP (env: ATL_TENANT ATL_AGENT ATL_KEY_VERSION ATL_SECRET ATL_URL ATL_MANIFEST)

Edit `atl-data/capabilities.json` to define tools, grants, limits. Malformed manifest = refuse to start.

Event fields: tenant_id, seq, event_id, ts, type, actor, correlation_id, causation_id, idempotency_key, payload, evidence[], prev_hash, hash, mac.

## 0.2 additions
- **Abandoned requests**: an idempotent request still `in_progress` after `limits.idem_lease_s` (default 120) is reconciled on the next retry. It is never re-executed. The client gets its recorded outcome if the tool had finished, otherwise `409 abandoned` with `executed: "no"` (tool never started, safe to retry with a new key) or `"unknown"` (started, no outcome recorded). A `tool.abandoned` event goes in the ledger.
- **Chain-only verification** (`atl verify T --chain-only`) checks structure only: anyone with database write access can rewrite events and recompute the chain and it still passes (the output now says so, `assurance: structure_only`). Give auditors an anchors file held outside the data dir (`ATL_ANCHOR_FILE`, or the `ATL_ANCHOR_WEBHOOK` receiver) and run `--chain-only --anchors FILE`: the ledger must match every anchored hash (`assurance: structure_and_anchors`). Keyed `atl verify` (master key) remains the strongest check. The webhook result is recorded as an `anchor.published` ledger event.
- **Erasure**: `atl erase TENANT HASH --reason ...` (or `POST /v1/admin/erase`) deletes one evidence blob after appending `evidence.erased {hash}`; `verify` accepts tombstoned blobs, and still fails on any other missing or corrupt blob. The SHA-256 stays in the ledger events that referenced it; for low-entropy personal data a hash can be guessable. Engineering support for a deletion workflow, not a compliance determination.
- **Policy constraints** per param: `enum`, `pattern` (whole-value regex), `min`/`max` for numbers (`max` on strings is still the length). Bad constraints refuse to start. Per-tool budget: `"rate_per_minute": N` on a tool denies with `tool_rate_limited` beyond N calls per minute per agent.
- **Admin reads** (`/v1/admin/events`, `/v1/admin/verify`) append `admin.read` events.
- Not changed: single static admin token, SQLite single writer, no tool-adapter mechanism (tools are hardcoded in `worker.py`), no asymmetric signatures (needs a non-stdlib crypto dependency).

## Executor
`ATL_EXECUTOR=subprocess` (default) or `docker`. Docker mode runs one container per call: `--network none --read-only --cap-drop ALL --no-new-privileges --pids-limit 64 --memory 256m --cpus 1 --user 65534:65534`, tmpfs `/tmp` noexec, per-tenant sandbox dir as the only writable path, `worker.py` read-only, wall-clock kill + `rm -f`. Image must be digest-pinned (`ATL_DOCKER_IMAGE`, default python:3.12-slim digest, must be pre-pulled; `--pull never`). Any docker error fails the call or refuses startup; there is no fallback to subprocess. The gateway must not mount the Docker socket (see docker-compose.yml).

## Master key
`ATL_KEY_PROVIDER` = `file` (default; `env` if only `ATL_MASTER_KEY_HEX` is set) | `env` | `aws-kms` (`ATL_KMS_KEY_ID`, boto3 imported lazily) | `vault` (`ATL_VAULT_ADDR`, `ATL_VAULT_TOKEN`; KV v2 via `ATL_VAULT_PATH`/`ATL_VAULT_MOUNT`, or `ATL_VAULT_MODE=transit` with `ATL_VAULT_KEY`). Non-file modes never write plaintext keys to disk. `env` rotation: set `ATL_MASTER_KEY_HEX`, `ATL_MASTER_KEY_VERSION=n`, keep old keys in `ATL_MASTER_KEY_HEX_V<k>`.
`python3 -m atl key rotate` creates a new master version and appends `key.rotated {master_version}` to every tenant ledger; events are MACed under the version in force before them, principals and anchors record the version they were issued under, so old data verifies as long as old master versions stay retrievable.

## Other
`bakeoff/suite.py`: shared tamper suite for ledger comparison (ATL adapter included; POM/SAL adapters must be supplied). `Dockerfile`, `Dockerfile.executor`, `docker-compose.yml`; CI in `../.github/workflows/atl.yml` (verify + CycloneDX SBOM).

Known limits: SQLite single writer; DB-backed single-node rate limits; Python policy evaluator (OPA not used); Docker mode needs host daemon access, so the compose gateway uses the subprocess worker inside a locked-down container; HashiCorp Vault and AWS KMS providers are tested against mocks only.
