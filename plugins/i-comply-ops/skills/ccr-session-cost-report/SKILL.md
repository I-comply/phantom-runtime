---
name: ccr-session-cost-report
description: Report token/cost usage and cost per turn for a Claude Code Remote session, and explain why cost per turn rises. Uses get_session and list_events result events.
---

# CCR session cost report

## Steps
1. Totals: `get_session` (omit `session_id` for the current session). Read `external_metadata.usage` (cost_usd, input/output/cache_read/cache_write tokens), `context_usage`, `rate_limit_info`.
2. Per-turn data: `list_events(session_id, kinds: ["result"], limit: 100)`. Page backward with `before_id` = previous page `first_id` until `has_more` is false.
3. Each result event carries `total_cost_usd`, cumulative per process. Per-turn cost = difference between consecutive values. A drop means the process restarted; treat the new value as the turn cost.
4. Check: sum of per-turn costs equals the session total.
5. Write a table (turn, cumulative, delta, output tokens) to the scratchpad; deliver with `SendUserFile`.
6. Account-level usage is not available from a session; say so.

## Why cost rises
Every turn rereads the whole context as cache read. Cost per turn grows with context size (observed: ~$0.17 to $0.32 per turn at ~300k context).

## Mitigation
Compact (`/compact`) or start a fresh session with a handoff prompt; scope to one repo; batch requests; attach only needed repos.
