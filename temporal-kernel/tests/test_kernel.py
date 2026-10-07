import shutil, sqlite3, sys, tempfile, threading, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tkernel import (EventLog, Machine, MachineError, Node, Rejected, IntegrityError, Conflict,
                     ReplayDivergence, Replay)

SPEC = {"id": "order", "initial": "reserve", "states": {
    "reserve": {"task": "reserve_stock", "max_attempts": 2, "on": {"ok": "charge"}},
    "charge": {"task": "charge_card", "on": {"ok": "done", "declined": "failed"}},
    "done": {"terminal": True}, "failed": {"terminal": True}}}


class Clock:
    def __init__(self): self.t = 1_000_000
    def __call__(self): return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.db = self.d / "log.db"
        self.clk = Clock()
        self.m = Machine(SPEC)
        self.log = EventLog(self.db)
        self.a = self.node("A")

    def node(self, name, log=None):
        return Node(log or EventLog(self.db), [self.m], node_id=name, lease_ms=1000, clock=self.clk)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)


class TestLifecycle(Base):
    def test_happy_path(self):
        self.a.start("w1", "order", {"sku": 7})
        t = self.a.claim("w1")
        self.assertEqual((t["name"], t["fence"], t["input"]), ("reserve_stock", 1, {"sku": 7}))
        self.assertIsNone(self.a.claim("w1"))  # already leased
        self.a.complete("w1", t["task_id"], t["fence"], "ok", {"qty": 1})
        t = self.a.claim("w1")
        self.assertEqual(t["ctx"], {"reserve_stock": {"qty": 1}})
        self.a.complete("w1", t["task_id"], t["fence"], "ok")
        s = self.a.state("w1")
        self.assertEqual((s["status"], s["mstate"]), ("completed", "done"))
        self.assertEqual(self.a.verify("w1"), len(self.log.read("w1")))

    def test_bad_trigger_rejected_and_not_logged(self):
        self.a.start("w1", "order")
        t = self.a.claim("w1")
        n = self.log.head("w1")[0]
        with self.assertRaises(Rejected):
            self.a.complete("w1", t["task_id"], t["fence"], "nope")
        self.assertEqual(self.log.head("w1")[0], n)

    def test_retry_then_fail(self):
        self.a.start("w1", "order")
        t = self.a.claim("w1"); self.a.fail("w1", t["task_id"], t["fence"], "boom")
        t = self.a.claim("w1"); self.assertEqual(t["attempt"], 2)
        self.a.fail("w1", t["task_id"], t["fence"], "boom2")
        s = self.a.state("w1")
        self.assertEqual((s["status"], s["error"]), ("failed", "boom2"))
        self.assertIsNone(self.a.claim("w1"))

    def test_start_twice_rejected(self):
        self.a.start("w1", "order")
        with self.assertRaises(Rejected):
            self.a.start("w1", "order", {"x": 1})

    def test_machine_validation(self):
        bad = dict(SPEC, initial="zzz")
        with self.assertRaises(MachineError):
            Machine(bad)
        with self.assertRaises(MachineError):
            Machine({"id": "x", "initial": "a", "states": {"a": {"task": "t", "on": {"ok": "nowhere"}}}})


class TestFailover(Base):
    def test_node_crash_lease_expiry_and_fencing(self):
        self.a.start("w1", "order")
        ta = self.a.claim("w1")          # node A leases, then "dies"
        b = self.node("B")
        self.assertIsNone(b.claim("w1"))  # lease still live
        self.clk.t += 1001
        tb = b.claim("w1")                # B recovers + leases
        self.assertEqual(tb["fence"], 2)
        with self.assertRaises(Rejected):  # zombie A wakes up and tries to finish
            self.a.complete("w1", ta["task_id"], ta["fence"], "ok")
        with self.assertRaises(Rejected):
            self.a.heartbeat("w1", ta["task_id"], ta["fence"])
        b.complete("w1", tb["task_id"], tb["fence"], "ok")
        self.assertEqual(self.a.state("w1")["mstate"], "charge")  # A sees B's progress

    def test_heartbeat_extends_lease(self):
        self.a.start("w1", "order")
        t = self.a.claim("w1")
        self.clk.t += 900
        self.a.heartbeat("w1", t["task_id"], t["fence"])
        self.clk.t += 900
        self.assertIsNone(self.node("B").claim("w1"))

    def test_concurrent_claims_single_winner(self):
        self.a.start("w1", "order")
        res, nodes = [], [self.node("N%d" % i) for i in range(8)]
        def go(n): res.append(n.claim("w1"))
        ts = [threading.Thread(target=go, args=(n,)) for n in nodes]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len([r for r in res if r]), 1)

    def test_fresh_node_replays_identical_state(self):
        self.a.start("w1", "order")
        t = self.a.claim("w1"); self.a.complete("w1", t["task_id"], t["fence"], "ok", {"k": 1})
        self.assertEqual(self.node("Z").state("w1"), self.a.state("w1"))


class TestPauseRollback(Base):
    def test_pause_resume(self):
        self.a.start("w1", "order")
        self.a.pause("w1", "maintenance")
        self.assertIsNone(self.a.claim("w1"))
        with self.assertRaises(Rejected):
            self.a.pause("w1")
        self.a.resume("w1")
        self.assertIsNotNone(self.a.claim("w1"))

    def test_inflight_completion_accepted_while_paused(self):
        self.a.start("w1", "order")
        t = self.a.claim("w1"); self.a.pause("w1")
        self.a.complete("w1", t["task_id"], t["fence"], "ok")
        self.assertIsNone(self.a.claim("w1"))
        self.assertEqual(self.a.state("w1")["mstate"], "charge")

    def test_rollback_to_checkpoint(self):
        self.a.start("w1", "order")
        t = self.a.claim("w1"); self.a.complete("w1", t["task_id"], t["fence"], "ok", {"r": 1})
        cp = self.a.checkpoint("w1", "after-reserve")
        t = self.a.claim("w1")                      # charge task leased, fence 2
        self.a.complete("w1", t["task_id"], t["fence"], "declined")
        self.assertEqual(self.a.state("w1")["mstate"], "failed")
        self.assertEqual(self.a.state("w1")["status"], "completed")
        # terminal workflows cannot be rolled back
        with self.assertRaises(Rejected):
            self.a.rollback("w1", cp["seq"])

    def test_rollback_mid_flight_fences_zombie(self):
        self.a.start("w1", "order")
        t = self.a.claim("w1"); self.a.complete("w1", t["task_id"], t["fence"], "ok", {"r": 1})
        cp = self.a.checkpoint("w1")
        zt = self.a.claim("w1")                     # charge leased with fence 2
        n_before = self.log.head("w1")[0]
        self.a.rollback("w1", cp["seq"], "bad price")
        self.assertEqual(self.log.head("w1")[0], n_before + 1)  # history only grows
        s = self.a.state("w1")
        self.assertEqual((s["status"], s["mstate"], s["tasks"][zt["task_id"]]["status"]), ("paused", "charge", "pending"))
        self.a.resume("w1")
        with self.assertRaises(Rejected):           # worker from discarded branch is stale
            self.a.complete("w1", zt["task_id"], zt["fence"], "ok")
        nt = self.a.claim("w1")
        self.assertEqual(nt["fence"], 3)
        self.a.complete("w1", nt["task_id"], nt["fence"], "ok")
        self.assertEqual(self.a.state("w1")["mstate"], "done")

    def test_rollback_requires_live_checkpoint(self):
        self.a.start("w1", "order")
        with self.assertRaises(Rejected):
            self.a.rollback("w1", 1)
        t = self.a.claim("w1"); self.a.complete("w1", t["task_id"], t["fence"], "ok")
        cp1 = self.a.checkpoint("w1")
        self.a.claim("w1")
        cp2 = self.a.checkpoint("w1")
        self.a.rollback("w1", cp1["seq"])
        with self.assertRaises(Rejected):           # cp2 belonged to the discarded branch
            self.a.rollback("w1", cp2["seq"])

    def test_checkpoint_hash_must_match_replay(self):
        self.a.start("w1", "order")
        r = self.a._load("w1")
        with self.assertRaises(Exception):
            r.clone().apply({"type": "checkpoint", "payload": {"state_hash": "00"}, "seq": 2})
        self.assertTrue(issubclass(ReplayDivergence, Exception))


class TestIntegrity(Base):
    def test_log_is_append_only(self):
        self.a.start("w1", "order")
        c = sqlite3.connect(self.db)
        for sql in ("UPDATE events SET type='x'", "DELETE FROM events"):
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute(sql)

    def test_tamper_detected(self):
        self.a.start("w1", "order")
        t = self.a.claim("w1"); self.a.complete("w1", t["task_id"], t["fence"], "ok", {"v": 1})
        c = sqlite3.connect(self.db)
        c.execute("DROP TRIGGER events_no_update")  # attacker with raw file access
        c.execute("UPDATE events SET payload=replace(payload,'\"v\":1','\"v\":2') WHERE seq=3")
        c.commit()
        with self.assertRaises(IntegrityError):
            self.a.verify("w1")

    def test_hmac_blocks_rechain(self):
        log = EventLog(self.d / "k.db", key=b"k" * 32)
        n = Node(log, [self.m], clock=self.clk)
        n.start("w1", "order")
        self.assertEqual(n.verify("w1"), 1)
        self.assertRaises(IntegrityError, EventLog(self.d / "k.db", key=b"x" * 32).verify, "w1")

    def test_optimistic_concurrency_and_idempotency(self):
        e = self.log.append("x", 0, "wf.started", {}, idem="i")
        self.assertTrue(self.log.append("x", 99, "wf.started", {}, idem="i").get("duplicate"))
        with self.assertRaises(Conflict):
            self.log.append("x", 0, "t", {})
        self.assertEqual(e["seq"], 1)


if __name__ == "__main__":
    unittest.main()
