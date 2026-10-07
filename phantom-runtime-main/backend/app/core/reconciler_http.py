"""HTTP transport for the reconciliation daemon: peer client + shared-secret auth.

Auth is a cluster-wide shared secret in ``X-Reconciler-Token`` (the DB-backed
API keys are tenant-scoped and don't fit node-to-node traffic). The secret is
sent in cleartext at the HTTP layer, so peer URLs must be https outside a
trusted private network.
"""
import asyncio
import hmac
import json
import urllib.request
from typing import Dict, Tuple
from urllib.parse import urlparse

TOKEN_HEADER = "X-Reconciler-Token"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def token_valid(supplied: str | None, secret: str | None) -> bool:
    if not secret or not supplied:
        return False
    return hmac.compare_digest(supplied.encode(), secret.encode())


def parse_peers(spec: str) -> Dict[str, str]:
    """'node-b=https://b:8001,node-c=https://c:8001' -> {id: base_url}."""
    peers: Dict[str, str] = {}
    for item in (s.strip() for s in spec.split(",")):
        if not item:
            continue
        node_id, sep, url = item.partition("=")
        if not sep or not node_id.strip() or urlparse(url).scheme not in ("http", "https"):
            raise ValueError(f"invalid RECONCILER_PEERS entry {item!r}; expected id=http(s)://host:port")
        peers[node_id.strip()] = url.strip().rstrip("/")
    return peers


class HttpPeer:
    def __init__(self, node_id: str, base_url: str, secret: str, timeout: float = 3.0):
        if urlparse(base_url).scheme not in ("http", "https"):
            raise ValueError("peer url must be http(s)")
        self.node_id, self.base_url, self.secret, self.timeout = node_id, base_url.rstrip("/"), secret, timeout

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(self.base_url + path, headers={TOKEN_HEADER: self.secret})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310 - scheme validated in __init__
            body = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("peer response too large")
        return json.loads(body)

    async def digest(self) -> Tuple[str, Dict[str, int]]:
        d = await asyncio.to_thread(self._get, "/api/reconciler/digest")
        return d["digest"], d["clock"]

    async def snapshot(self) -> dict:
        return await asyncio.to_thread(self._get, "/api/reconciler/snapshot")
