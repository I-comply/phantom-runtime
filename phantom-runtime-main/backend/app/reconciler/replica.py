import hashlib
import json
import threading
from typing import Any, Dict

from .crdt import crdt_from_dict
from .vclock import VectorClock


class Replica:
    """A node's CRDT state plus the vector clock of updates it has seen. Thread-safe."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self._lock = threading.RLock()
        self._objs: Dict[str, Any] = {}
        self._clock = VectorClock()

    def mutate(self, key: str, factory, fn) -> None:
        """Apply fn(crdt) to the object at key (created by factory if absent) and tick the clock."""
        with self._lock:
            obj = self._objs.get(key) or factory()
            fn(obj)
            self._objs[key] = obj
            self._clock = self._clock.tick(self.node_id)

    def get(self, key: str):
        with self._lock:
            return self._objs.get(key)

    @property
    def clock(self) -> VectorClock:
        with self._lock:
            return self._clock

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"clock": self._clock.to_dict(),
                    "objects": {k: v.to_dict() for k, v in sorted(self._objs.items())}}

    def digest(self) -> str:
        """SHA-256 over the canonical state (clock excluded; compared separately)."""
        return digest_of(self.snapshot()["objects"])

    def merge_snapshot(self, snap: Dict[str, Any]) -> bool:
        """CRDT-merge a remote snapshot. Returns True if local state changed."""
        remote = {k: crdt_from_dict(v) for k, v in snap["objects"].items()}
        remote_clock = VectorClock.from_dict(snap["clock"])
        with self._lock:
            before = self.digest()
            for k, r in remote.items():
                cur = self._objs.get(k)
                if cur is not None and cur.kind != r.kind:
                    raise ValueError(f"type conflict on {k!r}: {cur.kind} vs {r.kind}")
                self._objs[k] = r if cur is None else cur.merge(r)
            self._clock = self._clock.merge(remote_clock)
            return self.digest() != before


def digest_of(objects: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(objects, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
