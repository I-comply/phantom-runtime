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


# --- merge limits (peer snapshots are untrusted) ---

def snap_with(**obj_overrides):
    return {"clock": {"x": 1}, "objects": obj_overrides}


def test_rejects_oversized_snapshots():
    from app.reconciler import Limits
    r = Replica("a", Limits(max_objects=2, max_elements=3, max_snapshot_bytes=500))
    many = {f"k{i}": GCounter({"x": 1}).to_dict() for i in range(3)}
    with pytest.raises(ValueError):
        r.merge_snapshot(snap_with(**many))
    with pytest.raises(ValueError):
        r.merge_snapshot(snap_with(s=GCounter({f"n{i}": 1 for i in range(4)}).to_dict()))
    big = ORSet({(f"e{i}", "t") for i in range(3)})
    big.add("x" * 600, "t")
    with pytest.raises(ValueError):
        r.merge_snapshot(snap_with(s=big.to_dict()))
    assert r.get("k0") is None and r.digest() == Replica("b").digest()


def test_rejects_far_future_lww_but_accepts_current():
    import time
    r = Replica("a")
    with pytest.raises(ValueError):
        r.merge_snapshot(snap_with(v=LWWRegister("pwn", 32503680000000, "x").to_dict()))  # year 3000
    assert r.get("v") is None
    now = int(time.time() * 1000)
    assert r.merge_snapshot(snap_with(v=LWWRegister("ok", now, "x").to_dict()))
    assert r.get("v").value == "ok"


def test_rejects_huge_or_invalid_counters_and_clock():
    r = Replica("a")
    for bad in (2 ** 63, -1, True, "5", 1.5):
        with pytest.raises(ValueError):
            r.merge_snapshot(snap_with(c={"type": "gcounter", "counts": {"x": bad}}))
        with pytest.raises(ValueError):
            r.merge_snapshot({"clock": {"x": bad}, "objects": {}})
    with pytest.raises(ValueError):
        r.merge_snapshot({"clock": {"x": 10 ** 12}, "objects": {}})  # jump beyond max_clock_jump
    assert r.clock == VectorClock()


def test_type_conflict_keeps_local_and_is_atomic():
    a, b = Replica("a"), Replica("b")
    a.mutate("k", GCounter, lambda c: c.increment("a"))
    b.mutate("aaa", GCounter, lambda c: c.increment("b"))   # would merge cleanly
    b.mutate("k", ORSet, lambda s: s.add("x", "t"))
    before = a.digest()
    with pytest.raises(ValueError):
        a.merge_snapshot(b.snapshot())
    assert a.digest() == before and a.get("aaa") is None and a.get("k").kind == "gcounter"


@pytest.mark.parametrize("snap", [None, [], {}, {"clock": {}, "objects": []},
                                  {"clock": {}, "objects": {"c": {"type": "orset", "adds": "x", "removes": []}}},
                                  {"clock": {}, "objects": {"c": {"type": "lww", "ts": 1}}},
                                  {"clock": {}, "objects": {"c": {"type": "pncounter"}}}])
def test_malformed_snapshots_raise_valueerror_only(snap):
    with pytest.raises(ValueError):
        Replica("a").merge_snapshot(snap)


def test_malformed_snapshot_does_not_abort_cycle():
    a, b, c = Replica("a"), Replica("b"), Replica("c")
    cnt(c)
    class Bad(Link):
        def snapshot(self):
            return {"clock": {"b": 2 ** 63}, "objects": {}}
    bad = Bad(b)
    b.mutate("c", GCounter, lambda x: x.increment("b"))  # makes b's status differ so a fetches
    ev = ReconcilerDaemon(a, [bad, Link(c)]).tick()
    assert [e.merged for e in ev] == [False, True]
    assert a.get("c").value == 1


# --- replication policy and app wiring ---

def test_key_policy_allows_only_cluster_namespace():
    from app.reconciler.policy import cluster_key_policy as ok
    assert ok("cluster/epoch") and ok("cluster/heartbeat/node-1")
    for bad in ("events/1", "workspaces/abc/state", "cluster/", "cluster/Up", "cluster/a/b/c/d",
                "cluster/../x", "api_keys", "", "cluster/" + "a" * 65):
        assert not ok(bad), bad


def test_replica_enforces_key_policy_both_ways():
    from app.reconciler.policy import cluster_key_policy
    a = Replica("a", key_policy=cluster_key_policy)
    with pytest.raises(ValueError):
        a.mutate("tenant/1", GCounter, lambda c: c.increment("a"))
    with pytest.raises(ValueError):
        a.merge_snapshot(snap_with(**{"tenant/1": GCounter({"x": 1}).to_dict()}))
    assert a.merge_snapshot(snap_with(**{"cluster/ok": GCounter({"x": 1}).to_dict()}))


def test_lww_values_must_be_short_scalars():
    r = Replica("a")
    for bad in ({"tenant": "acme"}, ["x"], "x" * 2000):
        with pytest.raises(ValueError):
            r.merge_snapshot(snap_with(v=LWWRegister(bad, 1, "x").to_dict()))
    assert r.merge_snapshot(snap_with(v=LWWRegister("fine", 1, "x").to_dict()))


def test_build_reconciler_flag_and_validation():
    from app.reconciler.runtime import build_reconciler
    assert build_reconciler(False, None, 5) is None
    with pytest.raises(RuntimeError):
        build_reconciler(True, None, 5)
    with pytest.raises(RuntimeError):
        build_reconciler(True, "n1", 0)
    d = build_reconciler(True, "n1", 0.01)
    try:
        assert d.peers == [] and d._thread.is_alive()
    finally:
        d.stop()


def test_app_lifespan_default_off(client):
    assert client.app.state.reconciler is None
