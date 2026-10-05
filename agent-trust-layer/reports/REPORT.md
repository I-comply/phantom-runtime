# ATL code review, security scan and agent test report

Scope: `agent-trust-layer/` only. Date 2026-10-05.

## 1. Code review findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | High | Pre-auth failure limiter keyed by source IP only and checked before authentication: one identity (or a shared NAT/proxy address) sending ~30 bad requests/min got **every** agent behind that address, including valid ones, a 429. Found by the agent harness: 529 of 744 requests failed. | Fixed: limiter keyed by (source, tenant, agent) plus a 1000/min per-source backstop against identity spraying. 2 regression tests. |
| 2 | Medium | Docker sandbox dirs were `chmod 1777`. | Fixed: `chown 65534` + `0700`; 1777 only if the host cannot chown. |
| 3 | Medium | Data dir (db, evidence, keys, admin token) used default umask. | Fixed: `0700`. |
| 4 | Medium | Webhook/Vault/MCP `urlopen` accepted any scheme (`file:`, `ftp:`). | Fixed: `http_open` allows http/https only. |
| 5 | Low | HTTP body: negative `Content-Length` and no socket timeout (slowloris). | Fixed. |
| 6 | Low | Evidence `put` skipped rewriting a corrupt existing blob. | Fixed: rewrites on hash mismatch. |
| 7 | Low | Swallowed exception on container cleanup. | Fixed: logged to stderr. |

Earlier in this branch's history: tenants shared one sandbox directory (fixed in PR #6).

Open / tech debt (not changed):
- An idempotency row stays `in_progress` (409) if the process dies between execute and response write.
- Rate limits use the TCP peer address; behind a proxy all clients share one source (per-agent keying limits the blast radius).
- No TLS in the built-in server (terminate at a proxy); evidence stores request params in plaintext.
- SQLite single writer; Python policy evaluator.

## 2. Secrets and environment scan

- Pattern scan (AWS keys, private keys, key/secret/token assignments, 64-hex strings) over `agent-trust-layer/`: no hits outside test fixtures and the pinned image digest.
- Git tree: no `.env`, `master.key`, `admin.token` or `*.db` tracked. `.gitignore` covers `atl-data/`.
- Runtime secrets (`master.key`, `admin.token`) are created `0600` inside the `0700` data dir; non-file key providers never write plaintext keys (tested). Worker environment is `PATH` only (subprocess) or empty (Docker).
- Not run: gitleaks/trufflehog (not installed, no network install). The scan covers only this repo's `agent-trust-layer/` tree and its single commit history.

## 3. Vulnerability scan

- bandit 1.9.4 on `atl/`: before 2 High / 4 Medium / 6 Low; after 0 High / 0 Medium, 5 Low (subprocess usage with fixed argv, reviewed, accepted).
- Dependencies: stdlib only; `pip-audit` has nothing to audit. boto3 is an optional lazy import.
- Not run: container image CVE scan (trivy/grype unavailable here). CI generates CycloneDX SBOMs; run grype on them.

## 4. Agent test harness

`python3 -m harness.run_agents` starts a live HTTP gateway and one OS process per agent. Each agent runs 31 scenarios with expected status: honest calls, replay, forged signature, cross-tenant secret, unknown tool, param injection, path traversal, absolute path, oversize param, stale timestamp, destructive with/without approval, approval reuse, approval for a different intent, idempotency replay/reuse, 10-call burst. Afterwards it verifies each tenant ledger, checks attacker throttling, anchors, tampers and re-verifies.

| Run | Agents | Requests | Matched expectation | Throughput | p50 / p95 / p99 ms | Ledgers verify |
|---|---|---|---|---|---|---|
| subprocess, before fix | 24 | 744 | 215 (29%) | 92 rps | 29 / 1229 / 2401 | 3/3 |
| subprocess, after fix | 24 | 744 | **744 (100%)** | 128 rps | 65 / 741 / 1428 | 3/3 |
| docker, after fix | 6 | 186 | **186 (100%)** | 14 rps | 615 / 802 / 885 | 2/2 |

Also confirmed: attacker source throttled (429) while other agents unaffected; tamper of a payload detected (`content hash mismatch at seq 3`); `atl verify` exits 1 on tamper; no leftover containers after Docker run.

Graphs: `outcomes.png`, `latency_cdf.png`, `latency_by_scenario.png`, `throughput.png`. Raw data: `results_*.json`.

## 5. Assessment

- Security properties held under concurrent load: no cross-tenant access, replay, forged-signature, approval-reuse, path-escape or param-injection success in 930 scenario requests.
- The one significant defect was an availability flaw, now fixed; the harness is the regression test and is added to CI.
- Docker mode costs about 0.6 s per call (container start) versus about 0.03 s for the subprocess driver; use it where isolation matters more than latency.
- Caveats: 100% means expected outcomes, not a proof of absence of bugs; single machine, loopback network, small samples (docker 6 agents); the harness agents are scripted, not LLM-driven; Vault/KMS paths are mock-tested only; POM/SAL ledger bake-off still needs their code.
