"""State-based CRDTs. merge() is commutative, associative and idempotent."""
from typing import Any, Dict, Set, Tuple


class GCounter:
    kind = "gcounter"

    def __init__(self, counts: Dict[str, int] = None):
        self.counts: Dict[str, int] = dict(counts or {})

    def increment(self, node: str, n: int = 1) -> None:
        if n < 0:
            raise ValueError("GCounter cannot decrease")
        self.counts[node] = self.counts.get(node, 0) + n

    @property
    def value(self) -> int:
        return sum(self.counts.values())

    def merge(self, other: "GCounter") -> "GCounter":
        keys = self.counts.keys() | other.counts.keys()
        return GCounter({k: max(self.counts.get(k, 0), other.counts.get(k, 0)) for k in keys})

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.kind, "counts": dict(sorted(self.counts.items()))}

    @classmethod
    def from_dict(cls, d):
        return cls(d["counts"])


class PNCounter:
    kind = "pncounter"

    def __init__(self, p: GCounter = None, n: GCounter = None):
        self.p, self.n = p or GCounter(), n or GCounter()

    def add(self, node: str, delta: int) -> None:
        (self.p if delta >= 0 else self.n).increment(node, abs(delta))

    @property
    def value(self) -> int:
        return self.p.value - self.n.value

    def merge(self, other: "PNCounter") -> "PNCounter":
        return PNCounter(self.p.merge(other.p), self.n.merge(other.n))

    def to_dict(self):
        return {"type": self.kind, "p": self.p.to_dict(), "n": self.n.to_dict()}

    @classmethod
    def from_dict(cls, d):
        return cls(GCounter.from_dict(d["p"]), GCounter.from_dict(d["n"]))


class LWWRegister:
    """Last-writer-wins; ties on timestamp broken by node id, then canonical value, so merge is deterministic."""
    kind = "lww"

    def __init__(self, value: Any = None, ts: int = 0, node: str = ""):
        self.value, self.ts, self.node = value, ts, node

    def set(self, value: Any, ts: int, node: str) -> None:
        w = self.merge(LWWRegister(value, ts, node))
        self.value, self.ts, self.node = w.value, w.ts, w.node

    def _key(self) -> Tuple:
        import json
        return (self.ts, self.node, json.dumps(self.value, sort_keys=True, default=str))

    def merge(self, other: "LWWRegister") -> "LWWRegister":
        w = self if self._key() >= other._key() else other
        return LWWRegister(w.value, w.ts, w.node)

    def to_dict(self):
        return {"type": self.kind, "value": self.value, "ts": self.ts, "node": self.node}

    @classmethod
    def from_dict(cls, d):
        return cls(d["value"], d["ts"], d["node"])


class ORSet:
    """Observed-remove set: adds carry unique tags; remove tombstones observed tags, so concurrent re-add wins."""
    kind = "orset"

    def __init__(self, adds: Set[Tuple[str, str]] = None, removes: Set[Tuple[str, str]] = None):
        self.adds: Set[Tuple[str, str]] = set(adds or ())
        self.removes: Set[Tuple[str, str]] = set(removes or ())

    def add(self, element: str, tag: str) -> None:
        self.adds.add((element, tag))

    def remove(self, element: str) -> None:
        self.removes |= {e for e in self.adds if e[0] == element}

    @property
    def value(self) -> Set[str]:
        return {e for e, t in self.adds - self.removes}

    def merge(self, other: "ORSet") -> "ORSet":
        return ORSet(self.adds | other.adds, self.removes | other.removes)

    def to_dict(self):
        return {"type": self.kind, "adds": sorted(map(list, self.adds)), "removes": sorted(map(list, self.removes))}

    @classmethod
    def from_dict(cls, d):
        return cls({tuple(x) for x in d["adds"]}, {tuple(x) for x in d["removes"]})


_TYPES = {c.kind: c for c in (GCounter, PNCounter, LWWRegister, ORSet)}


def crdt_from_dict(d: Dict[str, Any]):
    try:
        return _TYPES[d["type"]].from_dict(d)
    except KeyError as e:
        raise ValueError(f"unknown or malformed CRDT: {e}") from e
