"""Which state may be replicated across instances. See docs/RECONCILER_REPLICATED_STATE.md."""
import re

# Only the `cluster/` namespace replicates: operational, non-tenant data.
# Anything else (events, workspaces, API keys, user or tenant payloads) never enters a Replica.
_KEY = re.compile(r"^cluster/[a-z0-9_-][a-z0-9_.-]{0,63}(/[a-z0-9_-][a-z0-9_.-]{0,63}){0,2}$")


def cluster_key_policy(key: str) -> bool:
    return bool(_KEY.fullmatch(key))
