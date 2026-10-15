import logging
from typing import List, Optional

from .daemon import Peer, ReconcilerDaemon
from .policy import cluster_key_policy
from .replica import Replica

log = logging.getLogger("phantom.reconciler")


def build_reconciler(enabled: bool, node_id: Optional[str], interval: float,
                     peers: Optional[List[Peer]] = None) -> Optional[ReconcilerDaemon]:
    """Return a started daemon, or None when disabled. Peers come from a transport (not part of this module)."""
    if not enabled:
        return None
    if not node_id:
        raise RuntimeError("RECONCILER_ENABLED requires RECONCILER_NODE_ID")
    if interval <= 0:
        raise RuntimeError("RECONCILER_INTERVAL must be positive")
    daemon = ReconcilerDaemon(Replica(node_id, key_policy=cluster_key_policy), peers or [], interval=interval)
    daemon.start()
    log.info("reconciler started: node=%s peers=%d", node_id, len(daemon.peers))
    return daemon
