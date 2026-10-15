# Temporal Kernel

Distributed orchestration node: deterministic state-machine workflows over an append-only, hash-chained event log. Python 3.9+, stdlib only.

    ./verify.sh                               # tests + demo
    python3 -m tkernel demo
    python3 -m tkernel verify <db> <wf_id>    # exit 1 on corruption

```python
log = EventLog("log.db")                      # EventLog(path, key=bytes) adds an HMAC per event
node = Node(log, [Machine(spec)], node_id="A", lease_ms=30000)
node.start("wf1", "order", {"sku": 1})
t = node.claim("wf1")                         # lease + fence token, or None
node.complete("wf1", t["task_id"], t["fence"], "ok", result)   # fail(...), heartbeat(...)
node.pause / resume / checkpoint / rollback(wf, to_seq) / recover / verify
```

## Model
- **Machine**: pure-data spec; every non-terminal state owns one task; task result trigger selects next state; `max_attempts` per state.
- **Log**: per-workflow streams, `PRIMARY KEY(wf_id, seq)`, `BEGIN IMMEDIATE` + `expected_seq` (optimistic concurrency), idempotency keys, SQLite triggers reject UPDATE/DELETE. Chain: `hash = sha256(canon(event incl. prev_hash))`.
- **State** = pure fold of the log (`replay.py`); no clock/randomness. Lease expiry and fences are carried in event payloads, so every node derives identical state.
- **Failover**: leases carry a monotonic fence. Expired lease -> any node `claim`s with fence+1; completions/heartbeats/failures with a stale fence are rejected (zombie nodes cannot corrupt state).
- **Checkpoint**: records the state hash; replay raises `ReplayDivergence` on mismatch (non-determinism or corruption).
- **Rollback**: logical. Appends `wf.rolled_back{to_seq}` to a live checkpoint; history is never rewritten. Restored state is paused, in-flight leases are reset to pending, fences keep increasing. Checkpoints past the target are discarded. Terminal workflows cannot be rolled back.
- **Pause/resume**: paused workflows issue no leases; in-flight completions are still accepted.

## Limits
SQLite single writer (all nodes must share the file/volume; no network replication or consensus). Without `key`, the chain detects corruption, not tampering by someone who can rewrite the file. Replay is full-history per cold node (cached afterwards); no snapshot-based fast start. Side effects of a rolled-back task are not undone: compensation is the workflow author's job (model it as states). Timers/signals are not implemented.
