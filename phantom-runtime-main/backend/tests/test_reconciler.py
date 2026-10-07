import asyncio

from app.core.reconciler import (GCounter, LocalPeer, LWWRegister, ORSet, PNCounter,
                                 ReconciliationDaemon, ReplicaState, VectorClock)


def run(c):
    return asyncio.run(c)


def test_vector_clock_compare():
    a, b = VectorClock({"x": 1}), VectorClock({"x": 1, "y": 1})
    assert a.compare(b) == "before" and b.compare(a) == "after" and a.compare(a) == "equal"
    assert VectorClock({"x": 2}).compare(VectorClock({"y": 1})) == "concurrent"


def test_crdt_merge_laws():
    a, b = GCounter({"a": 3}), GCounter({"a": 1, "b": 2})
    assert a.merge(b).to_dict() == b.merge(a).to_dict() == a.merge(b).merge(b).to_dict()
    assert a.merge(b).value == 5
    p = PNCounter(); p.incr("a", 5); q = PNCounter(); q.incr("b", -2)
    assert p.merge(q).value == 3
    r1, r2 = LWWRegister("old", 1, "a"), LWWRegister("new", 2, "b")
    assert r1.merge(r2).value == r2.merge(r1).value == "new"


def test_orset_add_wins_over_concurrent_remove():
    base = ORSet(); base.add("k")
    left = ORSet.from_dict(base.to_dict()); left.remove("k")
    right = ORSet.from_dict(base.to_dict()); right.add("k")
    assert left.merge(right).value == right.merge(left).value == {"k"}


def test_partition_heal_converges():
    async def go():
        sa, sb, sc = ReplicaState("a"), ReplicaState("b"), ReplicaState("c")
        for s in (sa, sb, sc):
            s.update("hits", GCounter())
        pa, pb, pc = LocalPeer(sa), LocalPeer(sb), LocalPeer(sc)
        da = ReconciliationDaemon(sa, [pb, pc], timeout=0.5)
        db = ReconciliationDaemon(sb, [pa, pc], timeout=0.5)
        dc = ReconciliationDaemon(sc, [pa, pb], timeout=0.5)

        pb.reachable = pc.reachable = False  # a isolated
        sa.crdts["hits"].incr("a", 4); sa.clock.tick("a")
        sb.crdts["hits"].incr("b", 2); sb.clock.tick("b")
        rep = await da.reconcile_once()
        assert rep.unreachable == {"b", "c"} and sa.crdts["hits"].value == 4

        pb.reachable = pc.reachable = True  # heal
        rep = await da.reconcile_once()
        assert rep.healed == {"b", "c"} and rep.merged == {"b"}
        await db.reconcile_once(); await dc.reconcile_once(); await da.reconcile_once()
        assert sa.digest() == sb.digest() == sc.digest()
        assert sc.crdts["hits"].value == 6
        assert (await da.reconcile_once()).drifted == set()
    run(go())


def test_daemon_loop_start_stop():
    async def go():
        sa, sb = ReplicaState("a"), ReplicaState("b")
        sb.update("n", GCounter({"b": 7}))
        d = ReconciliationDaemon(sa, [LocalPeer(sb)], interval=0.01)
        d.start()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if sa.digest() == sb.digest():
                break
        await d.stop()
        assert sa.digest() == sb.digest()
    run(go())
