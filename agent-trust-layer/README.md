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

## Executor
`ATL_EXECUTOR=subprocess` (default) or `docker`. Docker mode runs one container per call: `--network none --read-only --cap-drop ALL --no-new-privileges --pids-limit 64 --memory 256m --cpus 1 --user 65534:65534`, tmpfs `/tmp` noexec, per-tenant sandbox dir as the only writable path, `worker.py` read-only, wall-clock kill + `rm -f`. Image must be digest-pinned (`ATL_DOCKER_IMAGE`, default python:3.12-slim digest, must be pre-pulled; `--pull never`). Any docker error fails the call or refuses startup; there is no fallback to subprocess. The gateway must not mount the Docker socket (see docker-compose.yml).

## Master key
`ATL_KEY_PROVIDER` = `file` (default; `env` if only `ATL_MASTER_KEY_HEX` is set) | `env` | `aws-kms` (`ATL_KMS_KEY_ID`, boto3 imported lazily) | `vault` (`ATL_VAULT_ADDR`, `ATL_VAULT_TOKEN`; KV v2 via `ATL_VAULT_PATH`/`ATL_VAULT_MOUNT`, or `ATL_VAULT_MODE=transit` with `ATL_VAULT_KEY`). Non-file modes never write plaintext keys to disk. `env` rotation: set `ATL_MASTER_KEY_HEX`, `ATL_MASTER_KEY_VERSION=n`, keep old keys in `ATL_MASTER_KEY_HEX_V<k>`.
`python3 -m atl key rotate` creates a new master version and appends `key.rotated {master_version}` to every tenant ledger; events are MACed under the version in force before them, principals and anchors record the version they were issued under, so old data verifies as long as old master versions stay retrievable.

## ZK identity assertion
`atl/zkid.py` + `atl/groth16.py`: Groth16 (BN254) proof that a registered credential commitment `C = mimc(secret, mimc(permission_mask, salt))` permits tool T, bound to a single-use verifier nonce, tenant, agent and tool. Private: principal secret, permission mask, `salt` = digest(session config, env/tool tokens). Public: C, tool selector, challenge. Optional dependency `pip install py_ecc` (tests skip without it). Full-size circuit: 830 constraints, ~25 s setup, ~25 s prove, ~1 s verify (pure Python). Single-party trusted setup; use a multi-party ceremony and a native prover for production. Not yet wired into the gateway.

## Other
`bakeoff/suite.py`: shared tamper suite for ledger comparison (ATL adapter included; POM/SAL adapters must be supplied). `Dockerfile`, `Dockerfile.executor`, `docker-compose.yml`; CI in `../.github/workflows/atl.yml` (verify + CycloneDX SBOM).

Known limits: SQLite single writer; DB-backed single-node rate limits; Python policy evaluator (OPA not used); Docker mode needs host daemon access, so the compose gateway uses the subprocess worker inside a locked-down container; HashiCorp Vault and AWS KMS providers are tested against mocks only.
