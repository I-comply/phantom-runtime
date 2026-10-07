# Reconciler: replicated-state spec

Applies to `phantom-runtime-main/backend/app/reconciler`.

## What replicates

Only keys in the `cluster/` namespace, matching
`^cluster/<seg>(/<seg>){0,2}$`, `<seg>` = `[a-z0-9_-][a-z0-9_.-]{0,63}`, key length <= 200.
Enforced by `app.reconciler.policy.cluster_key_policy` in both directions:
`Replica.mutate` (local writes) and `Replica.merge_snapshot` (peer snapshots). A snapshot containing any
other key is rejected whole.

## What never replicates

Events, workspaces, snapshots, plugins, strategies, API keys, RBAC data, and any per-tenant or per-user
payload. No application table is read into or written from a Replica.

## Value rules

- Counters (GCounter/PNCounter): non-negative integers up to 2^53.
- LWW registers: scalar only (null, bool, number, or string <= 1024 chars); timestamps are unix ms and
  rejected if more than 5 minutes ahead of local time.
- OR-sets: string elements and tags only.
- Snapshot bounds: see `Limits` (objects, bytes, elements per object, clock nodes, clock jump).

## Wiring

- Off by default. `RECONCILER_ENABLED=true` starts it in the app lifespan; requires `RECONCILER_NODE_ID`;
  `RECONCILER_INTERVAL` (seconds, default 5).
- No transport is included, so the daemon runs with zero peers and does nothing until a transport PR adds
  authenticated peers. No endpoint is exposed.

## Adding a new replicated key

Requires admin approval and an update to this document. Do not widen the policy to cover tenant data.
