"""Cross-instance state reconciliation daemon.

Each node holds a ``ReplicaState`` (named CRDTs + a vector clock). The daemon
polls peers, hashes local state, compares it with peer digests and the consensus
vector clock (pointwise max of all reachable clocks), and merges peer state via
CRDT joins when drift is found or a partition heals.

Merges are commutative, associative and idempotent, so repeated or reordered
exchanges converge. Transport is abstracted (``Peer``); the digest is a
corruption/drift detector, not an authenticity guarantee — authenticate the
transport separately.
"""
import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, Set, Tuple

log = logging.getLogger("phantom.reconciler")


class VectorClock:
    def __init__(self, counts: Optional[Dict[str, int]] = None):
        self.counts: Dict[str, int] = dict(counts or {})

    def tick(self, node: str) -> "VectorClock":
        self.counts[node] = self.counts.get(node, 0) + 1
        return self

    def merge(self, other: "VectorClock") -> "VectorClock":
        out = dict(self.counts)
        for k, v in other.counts.items():
            out[k] = max(out.get(k, 0), v)
        return VectorClock(out)

    def compare(self, other: "VectorClock") -> str:
        """'equal' | 'before' | 'after' | 'concurrent' (self relative to other)."""
        keys = set(self.counts) | set(other.counts)
        lt = any(self.counts.get(k, 0) < other.counts.get(k, 0) for k in keys)
        gt = any(self.counts.get(k, 0) > other.counts.get(k, 0) for k in keys)
        if lt and gt:
            return "concurrent"
        return "before" if lt else "after" if gt else "equal"

    def to_dict(self) -> Dict[str, int]:
        return dict(sorted(self.counts.items()))

    @classmethod
    def from_dict(cls, d: Dict[str, int]) -> "VectorClock":
        return cls(d)


class GCounter:
    kind = "gcounter"

    def __init__(self, counts: Optional[Dict[str, int]] = None):
        self.counts: Dict[str, int] = dict(counts or {})

    def incr(self, node: str, n: int = 1) -> None:
        if n < 0:
            raise ValueError("GCounter only grows")
        self.counts[node] = self.counts.get(node, 0) + n

    @property
    def value(self) -> int:
        return sum(self.counts.values())

    def merge(self, other: "GCounter") -> "GCounter":
        keys = set(self.counts) | set(other.counts)
        return GCounter({k: max(self.counts.get(k, 0), other.counts.get(k, 0)) for k in keys})

    def to_dict(self):
        return {"counts": dict(sorted(self.counts.items()))}

    @classmethod
    def from_dict(cls, d):
        return cls(d["counts"])


class PNCounter:
    kind = "pncounter"

    def __init__(self, p: Optional[GCounter] = None, n: Optional[GCounter] = None):
        self.p, self.n = p or GCounter(), n or GCounter()

    def incr(self, node: str, k: int = 1) -> None:
        (self.p if k >= 0 else self.n).incr(node, abs(k))

    @property
    def value(self) -> int:
        return self.p.value - self.n.value

    def merge(self, other: "PNCounter") -> "PNCounter":
        return PNCounter(self.p.merge(other.p), self.n.merge(other.n))

    def to_dict(self):
        return {"p": self.p.to_dict(), "n": self.n.to_dict()}

    @classmethod
    def from_dict(cls, d):
        return cls(GCounter.from_dict(d["p"]), GCounter.from_dict(d["n"]))


class LWWRegister:
    """Last-writer-wins; ties on timestamp broken by node id, then value repr."""
    kind = "lww"

    def __init__(self, value=None, ts: float = 0.0, node: str = ""):
        self.value, self.ts, self.node = value, ts, node

    def set(self, value, ts: float, node: str) -> None:
        if self._key(ts, node, value) > self._key(self.ts, self.node, self.value):
            self.value, self.ts, self.node = value, ts, node

    @staticmethod
    def _key(ts, node, value) -> Tuple[float, str, str]:
        return (ts, node, json.dumps(value, sort_keys=True, default=str))

    def merge(self, other: "LWWRegister") -> "LWWRegister":
        a, b = self, other
        win = a if self._key(a.ts, a.node, a.value) >= self._key(b.ts, b.node, b.value) else b
        return LWWRegister(win.value, win.ts, win.node)

    def to_dict(self):
        return {"value": self.value, "ts": self.ts, "node": self.node}

    @classmethod
    def from_dict(cls, d):
        return cls(d["value"], d["ts"], d["node"])


class ORSet:
    """Observed-remove set: add wins over a concurrent remove."""
    kind = "orset"

    def __init__(self, adds: Optional[Dict[str, Set[str]]] = None, tombstones: Optional[Set[str]] = None):
        self.adds: Dict[str, Set[str]] = {k: set(v) for k, v in (adds or {}).items()}
        self.tombstones: Set[str] = set(tombstones or ())

    def add(self, elem: str) -> None:
        self.adds.setdefault(elem, set()).add(uuid.uuid4().hex)

    def remove(self, elem: str) -> None:
        self.tombstones |= self.adds.get(elem, set())

    @property
    def value(self) -> Set[str]:
        return {e for e, tags in self.adds.items() if tags - self.tombstones}

    def merge(self, other: "ORSet") -> "ORSet":
        adds: Dict[str, Set[str]] = {}
        for src in (self.adds, other.adds):
            for e, tags in src.items():
                adds.setdefault(e, set()).update(tags)
        return ORSet(adds, self.tombstones | other.tombstones)

    def to_dict(self):
        return {"adds": {e: sorted(t) for e, t in sorted(self.adds.items())},
                "tombstones": sorted(self.tombstones)}

    @classmethod
    def from_dict(cls, d):
        return cls({e: set(t) for e, t in d["adds"].items()}, set(d["tombstones"]))


CRDT_TYPES = {c.kind: c for c in (GCounter, PNCounter, LWWRegister, ORSet)}


def _encode(crdt) -> dict:
    return {"kind": crdt.kind, "data": crdt.to_dict()}


def _decode(d: dict):
    return CRDT_TYPES[d["kind"]].from_dict(d["data"])


class ReplicaState:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.crdts: Dict[str, object] = {}
        self.clock = VectorClock()

    def update(self, name: str, crdt) -> None:
        """Install/replace a CRDT locally and advance this node's clock."""
        self.crdts[name] = crdt
        self.clock.tick(self.node_id)

    def snapshot(self) -> dict:
        return {"clock": self.clock.to_dict(),
                "crdts": {k: _encode(v) for k, v in sorted(self.crdts.items())}}

    def digest(self) -> str:
        """Hash of the CRDT content only. Clocks are compared separately so two
        replicas with identical content but different tick histories still match."""
        body = {k: _encode(v) for k, v in sorted(self.crdts.items())}
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def merge_snapshot(self, snap: dict) -> bool:
        """Join a peer snapshot into local state. Returns True if local content changed."""
        before = self.digest()
        for name, enc in snap["crdts"].items():
            remote = _decode(enc)
            local = self.crdts.get(name)
            if local is not None and local.kind != remote.kind:
                log.error("type conflict on %s: %s vs %s; keeping local", name, local.kind, remote.kind)
                continue
            self.crdts[name] = remote if local is None else local.merge(remote)
        self.clock = self.clock.merge(VectorClock.from_dict(snap["clock"]))
        return self.digest() != before


class Peer(Protocol):
    node_id: str

    async def digest(self) -> Tuple[str, Dict[str, int]]: ...
    async def snapshot(self) -> dict: ...


class LocalPeer:
    """In-process peer wrapping another ReplicaState; ``reachable`` simulates partitions."""

    def __init__(self, state: ReplicaState):
        self.state, self.node_id, self.reachable = state, state.node_id, True

    async def digest(self):
        if not self.reachable:
            raise ConnectionError(self.node_id)
        return self.state.digest(), self.state.clock.to_dict()

    async def snapshot(self):
        if not self.reachable:
            raise ConnectionError(self.node_id)
        return self.state.snapshot()


@dataclass
class ReconcileReport:
    drifted: Set[str] = field(default_factory=set)
    healed: Set[str] = field(default_factory=set)
    unreachable: Set[str] = field(default_factory=set)
    merged: Set[str] = field(default_factory=set)
    consensus_clock: Dict[str, int] = field(default_factory=dict)


class ReconciliationDaemon:
    def __init__(self, state: ReplicaState, peers, interval: float = 5.0, timeout: float = 3.0):
        self.state, self.peers = state, list(peers)
        self.interval, self.timeout = interval, timeout
        self._partitioned: Set[str] = set()
        self._task: Optional[asyncio.Task] = None

    async def _probe(self, peer):
        try:
            return peer.node_id, await asyncio.wait_for(peer.digest(), self.timeout)
        except Exception as e:
            log.warning("peer %s unreachable: %r", peer.node_id, e)
            return peer.node_id, None

    async def reconcile_once(self) -> ReconcileReport:
        rep = ReconcileReport()
        probes = await asyncio.gather(*(self._probe(p) for p in self.peers))
        by_id = {p.node_id: p for p in self.peers}
        reachable: Dict[str, Tuple[str, Dict[str, int]]] = {}
        for nid, res in probes:
            if res is None:
                rep.unreachable.add(nid)
                self._partitioned.add(nid)
            else:
                reachable[nid] = res
                if nid in self._partitioned:
                    rep.healed.add(nid)
                    self._partitioned.discard(nid)

        consensus = self.state.clock
        for _, clk in reachable.values():
            consensus = consensus.merge(VectorClock.from_dict(clk))
        rep.consensus_clock = consensus.to_dict()

        local_hash = self.state.digest()
        for nid, (h, clk) in reachable.items():
            if h == local_hash and nid not in rep.healed:
                continue  # same content; clock-only skew needs no merge
            if h != local_hash:
                rep.drifted.add(nid)
            try:
                snap = await asyncio.wait_for(by_id[nid].snapshot(), self.timeout)
            except Exception as e:
                log.warning("snapshot from %s failed: %r", nid, e)
                rep.unreachable.add(nid)
                self._partitioned.add(nid)
                continue
            if self.state.merge_snapshot(snap):
                rep.merged.add(nid)
            local_hash = self.state.digest()
        return rep

    async def _run(self):
        while True:
            try:
                rep = await self.reconcile_once()
                if rep.drifted or rep.healed:
                    log.info("reconcile: drifted=%s healed=%s merged=%s", rep.drifted, rep.healed, rep.merged)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("reconcile cycle failed")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
