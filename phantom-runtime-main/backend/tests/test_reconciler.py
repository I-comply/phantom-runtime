import itertools
import threading

import pytest

from app.reconciler import (GCounter, LWWRegister, ORSet, PNCounter, Replica, ReconcilerDaemon,
                            DriftKind, PeerError, VectorClock, Ordering)
from app.reconciler.daemon import peer_status


class Link:
    """In-memory peer; `up` simulates a partition."""
    def __init__(self, replica):
        self.replica, self.node_id, self.up = replica, replica.node_id, True

    def status(self):
        if not self.up:
            raise PeerError("partitioned")
        return peer_status(self.replica)

    def snapshot(self):
        if not self.up:
            raise PeerError("partitioned")
        return self.replica.snapshot()


def cnt(r, key="c", n=1):
    r.mutate(key, GCounter, lambda c: c.increment(r.node_id, n))


def test_vclock_ordering():
    a = VectorClock().tick("a")
    b = a.tick("b")
    assert a.compare(b) == Ordering.BEFORE and b.compare(a) == Ordering.AFTER
    assert a.tick("a").compare(b) == Ordering.CONCURRENT
    assert a.compare(VectorClock({"a": 1})) == Ordering.EQUAL


def test_crdt_merge_laws():
    xs = []
    for i, n in enumerate("abc"):
        s = ORSet(); s.add(f"e{i}", f"t{i}"); s.add("shared", n)
        if i == 1:
            s.remove("shared")
        xs.append(s)
    results = {frozenset(__import__("functools").reduce(lambda x, y: x.merge(y), p).value)
               for p in itertools.permutations(xs)}
    assert len(results) == 1
    assert xs[0].merge(xs[0]).value == xs[0].value
    r1, r2 = LWWRegister("x", 5, "a"), LWWRegister("y", 5, "b")
    assert r1.merge(r2).value == r2.merge(r1).value == "y"
    p = PNCounter(); p.add("a", 5); p.add("a", -2)
    assert p.merge(p).value == 3


def test_orset_concurrent_add_wins_over_remove():
    a, b = ORSet(), ORSet()
    a.add("x", "t1"); b = b.merge(a)
    b.remove("x"); a.add("x", "t2")
    assert "x" in a.merge(b).value and "x" in b.merge(a).value


def test_converges_after_partition_heals():
    a, b, c = Replica("a"), Replica("b"), Replica("c")
    links = {r.node_id: Link(r) for r in (a, b, c)}
    daemons = [ReconcilerDaemon(r, [links[o.node_id] for o in (a, b, c) if o is not r]) for r in (a, b, c)]
    events = []
    daemons[0].on_event = events.append
    cnt(a); cnt(b); cnt(c)
    for d in daemons: d.tick()
    for d in daemons: d.tick()
    assert a.digest() == b.digest() == c.digest()

    links["c"].up = False                      # partition c away
    cnt(a, n=2); cnt(c, n=10)
    for d in daemons[:2]: d.tick()
    assert a.digest() == b.digest() != c.digest()
    assert daemons[0].tick() == []             # partitioned peer: no event, no crash

    links["c"].up = True                       # heal
    evs = daemons[0].tick()
    assert evs and evs[0].healed_partition and evs[0].kind == DriftKind.CONCURRENT
    for d in daemons: d.tick()
    assert a.digest() == b.digest() == c.digest()
    assert a.get("c").value == 15


def test_equal_clock_hash_mismatch_flagged_corrupt():
    a, b = Replica("a"), Replica("b")
    cnt(a); b.merge_snapshot(a.snapshot())
    b.get("c").counts["a"] = 99                # silent damage, clock unchanged
    ev = ReconcilerDaemon(a, [Link(b)]).tick()
    assert ev and ev[0].kind == DriftKind.CORRUPT and ev[0].merged


def test_bad_snapshot_rejected_not_fatal():
    a, b = Replica("a"), Replica("b")
    cnt(b)
    class Bad(Link):
        def snapshot(self):
            return {"clock": {}, "objects": {"c": {"type": "nope"}}}
    ev = ReconcilerDaemon(a, [Bad(b)]).tick()
    assert ev and not ev[0].merged and a.get("c") is None


def test_type_conflict_rejected():
    a, b = Replica("a"), Replica("b")
    a.mutate("k", GCounter, lambda c: c.increment("a"))
    b.mutate("k", ORSet, lambda s: s.add("x", "t"))
    with pytest.raises(ValueError):
        a.merge_snapshot(b.snapshot())


def test_background_thread_starts_and_stops():
    a, b = Replica("a"), Replica("b")
    cnt(b)
    d = ReconcilerDaemon(a, [Link(b)], interval=0.01)
    d.start()
    for _ in range(200):
        if a.get("c"):
            break
        threading.Event().wait(0.01)
    d.stop()
    assert a.digest() == b.digest()
