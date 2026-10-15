import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict

from .crdt import crdt_from_dict
from .vclock import VectorClock


@dataclass(frozen=True)
class Limits:
    """Bounds applied to every peer-supplied snapshot. Violations raise ValueError; nothing is merged."""
    max_objects: int = 1000
    max_snapshot_bytes: int = 1 << 20
    max_elements: int = 10_000          # per object: counter entries / set tags
    max_clock_nodes: int = 1000
    max_counter: int = 2 ** 53          # any counter or clock value
    max_clock_jump: int = 10 ** 9       # remote clock value minus local value for the same node
    max_lww_future_skew_ms: int = 5 * 60 * 1000  # LWW ts is unix milliseconds
    max_key_len: int = 200
    max_lww_value_len: int = 1024
    now_ms: Callable[[], int] = field(default=lambda: int(time.time() * 1000), compare=False)


def _count(v: Any, lim: Limits, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > lim.max_counter:
        raise ValueError(f"{what}: invalid counter {v!r}")
    return v


def _counts(d: Any, lim: Limits, what: str) -> None:
    if not isinstance(d, dict) or len(d) > lim.max_elements:
        raise ValueError(f"{what}: malformed or too many entries")
    for k, v in d.items():
        if not isinstance(k, str):
            raise ValueError(f"{what}: non-string node id")
        _count(v, lim, what)


def _tags(v: Any, lim: Limits, what: str) -> None:
    if not isinstance(v, list) or len(v) > lim.max_elements:
        raise ValueError(f"{what}: malformed or too many elements")
    for e in v:
        if not (isinstance(e, list) and len(e) == 2 and all(isinstance(x, str) for x in e)):
            raise ValueError(f"{what}: malformed element")


KeyPolicy = Callable[[str], bool]


def validate_snapshot(snap: Any, lim: Limits, local_clock: VectorClock, key_ok: KeyPolicy = None) -> None:
    if not isinstance(snap, dict) or not isinstance(snap.get("objects"), dict) \
            or not isinstance(snap.get("clock"), dict):
        raise ValueError("malformed snapshot")
    try:
        size = len(json.dumps(snap, separators=(",", ":")))
    except (TypeError, ValueError) as e:
        raise ValueError(f"snapshot not serializable: {e}") from e
    if size > lim.max_snapshot_bytes:
        raise ValueError(f"snapshot too large: {size} bytes")
    if len(snap["objects"]) > lim.max_objects:
        raise ValueError("too many objects")
    clock = snap["clock"]
    if len(clock) > lim.max_clock_nodes:
        raise ValueError("clock has too many nodes")
    local = local_clock.to_dict()
    for node, v in clock.items():
        if not isinstance(node, str):
            raise ValueError("clock: non-string node id")
        _count(v, lim, "clock")
        if v - local.get(node, 0) > lim.max_clock_jump:
            raise ValueError(f"clock jump too large for node {node!r}")
    ceiling = lim.now_ms() + lim.max_lww_future_skew_ms
    for key, o in snap["objects"].items():
        if not isinstance(key, str) or not isinstance(o, dict) or len(key) > lim.max_key_len:
            raise ValueError("malformed object")
        if key_ok is not None and not key_ok(key):
            raise ValueError(f"key not replicable: {key!r}")
        t = o.get("type")
        if t == "gcounter":
            _counts(o.get("counts"), lim, key)
        elif t == "pncounter":
            for part in ("p", "n"):
                sub = o.get(part)
                if not isinstance(sub, dict):
                    raise ValueError(f"{key}: malformed pncounter")
                _counts(sub.get("counts"), lim, key)
        elif t == "lww":
            ts = o.get("ts")
            _count(ts, lim, f"{key} ts")
            if ts > ceiling:
                raise ValueError(f"{key}: LWW timestamp too far in the future")
            if not isinstance(o.get("node"), str):
                raise ValueError(f"{key}: malformed lww")
            v = o.get("value")
            if not (v is None or isinstance(v, (bool, int, float))
                    or (isinstance(v, str) and len(v) <= lim.max_lww_value_len)):
                raise ValueError(f"{key}: LWW value must be a short scalar")
        elif t == "orset":
            _tags(o.get("adds"), lim, key)
            _tags(o.get("removes"), lim, key)
        else:
            raise ValueError(f"{key}: unknown CRDT type {t!r}")


class Replica:
    """A node's CRDT state plus the vector clock of updates it has seen. Thread-safe."""

    def __init__(self, node_id: str, limits: Limits = None, key_policy: KeyPolicy = None):
        self.node_id = node_id
        self.key_policy = key_policy
        self.limits = limits or Limits()
        self._lock = threading.RLock()
        self._objs: Dict[str, Any] = {}
        self._clock = VectorClock()

    def mutate(self, key: str, factory, fn) -> None:
        """Apply fn(crdt) to the object at key (created by factory if absent) and tick the clock."""
        if self.key_policy is not None and not self.key_policy(key):
            raise ValueError(f"key not replicable: {key!r}")
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
        """Validate then CRDT-merge a remote snapshot, all-or-nothing. Returns True if local state changed.

        Raises ValueError on any limit violation, malformed input or type conflict; local state is untouched.
        """
        with self._lock:
            validate_snapshot(snap, self.limits, self._clock, self.key_policy)
            try:
                remote = {k: crdt_from_dict(v) for k, v in snap["objects"].items()}
            except (KeyError, TypeError) as e:
                raise ValueError(f"malformed snapshot: {e}") from e
            if len(set(self._objs) | set(remote)) > self.limits.max_objects:
                raise ValueError("too many objects after merge")
            merged = {}
            for k, r in remote.items():
                cur = self._objs.get(k)
                if cur is not None and cur.kind != r.kind:
                    raise ValueError(f"type conflict on {k!r}: {cur.kind} vs {r.kind}")
                merged[k] = r if cur is None else cur.merge(r)
            before = self.digest()
            self._objs.update(merged)
            self._clock = self._clock.merge(VectorClock.from_dict(snap["clock"]))
            return self.digest() != before


def digest_of(objects: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(objects, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
