from enum import Enum
from typing import Dict, Mapping


class Ordering(str, Enum):
    EQUAL = "equal"
    BEFORE = "before"
    AFTER = "after"
    CONCURRENT = "concurrent"


class VectorClock:
    __slots__ = ("_c",)

    def __init__(self, counters: Mapping[str, int] = ()):
        self._c: Dict[str, int] = {k: int(v) for k, v in dict(counters).items() if v > 0}

    def tick(self, node: str) -> "VectorClock":
        c = dict(self._c)
        c[node] = c.get(node, 0) + 1
        return VectorClock(c)

    def merge(self, other: "VectorClock") -> "VectorClock":
        c = dict(self._c)
        for k, v in other._c.items():
            if v > c.get(k, 0):
                c[k] = v
        return VectorClock(c)

    def compare(self, other: "VectorClock") -> Ordering:
        le = all(v <= other._c.get(k, 0) for k, v in self._c.items())
        ge = all(v <= self._c.get(k, 0) for k, v in other._c.items())
        if le and ge:
            return Ordering.EQUAL
        if le:
            return Ordering.BEFORE
        if ge:
            return Ordering.AFTER
        return Ordering.CONCURRENT

    def to_dict(self) -> Dict[str, int]:
        return dict(self._c)

    @classmethod
    def from_dict(cls, d: Mapping[str, int]) -> "VectorClock":
        return cls(d)

    def __eq__(self, other):
        return isinstance(other, VectorClock) and self._c == other._c

    def __hash__(self):
        return hash(frozenset(self._c.items()))

    def __repr__(self):
        return f"VectorClock({self._c})"


def consensus(clocks) -> VectorClock:
    """Pointwise max over all given clocks: the least clock dominating every replica."""
    out = VectorClock()
    for c in clocks:
        out = out.merge(c)
    return out
