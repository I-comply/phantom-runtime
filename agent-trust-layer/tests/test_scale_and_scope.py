"""Append cost at scale, the unprotected window after the last anchor, per-agent sandboxes, path-like ids."""
import json, shutil, sqlite3, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.gateway import Core
from atl.client import sign_request
from atl.util import valid_id
from atl.policy import Policy, PolicyError

ROOT = Path(__file__).resolve().parent.parent
T = "acme"


class Base(unittest.TestCase):
    manifest = None

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        doc = json.loads((ROOT / "capabilities.json").read_text())
        if self.manifest:
            doc["limits"].update(self.manifest)
        (self.d / "capabilities.json").write_text(json.dumps(doc))
        self.c = Core(self.d)
        self.w = self.c.admin_principal("issue", T, "writer")
        self.o = self.c.admin_principal("issue", T, "other")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def call(self, who, action, params):
        p = self.w if who == "writer" else self.o
        return self.c.invoke(sign_request(p["secret"], T, who, p["key_version"], action, params))


class TestAppendCost(Base):
    def test_latest_key_rotation_lookup_uses_an_index(self):
        plan = " ".join(r[3] for r in self.c.db.conn().execute(
            "EXPLAIN QUERY PLAN SELECT payload FROM events WHERE tenant_id=? AND type='key.rotated' ORDER BY seq DESC LIMIT 1", (T,)))
        self.assertIn("events_keyrot", plan)  # used to be a walk over the tenant's whole ledger

    def test_append_cost_does_not_grow_with_ledger_size(self):
        def batch(n):
            t0 = time.perf_counter()
            for i in range(n):
                self.c.ledger.append(T, "bench.event", "bench", {"i": i})
            return (time.perf_counter() - t0) / n
        small = batch(200)
        for _ in range(5):
            batch(600)  # ~3,000 events
        large = batch(200)
        self.assertLess(large, small * 4, (small, large))

    def test_verify_all_streams_and_still_works(self):
        for i in range(2500):
            self.c.ledger.append(T, "bench.event", "bench", {"i": i})
        self.assertEqual(self.c.verify_all(T)["count"], 2500 + 2)  # + identity.issue x2
        self.assertEqual(len(list(self.c.ledger.iter_events(T, chunk=100))), 2502)


class TestAnchorWindow(Base):
    def forge_tail(self, n):
        conn = sqlite3.connect(self.d / "atl.db")
        conn.execute("DROP TRIGGER events_no_delete")
        conn.execute("DELETE FROM events WHERE tenant_id=? AND seq > (SELECT MAX(seq)-? FROM events WHERE tenant_id=?)", (T, n, T))
        conn.commit(); conn.close()

    def test_anchor_all_anchors_only_tenants_that_grew(self):
        self.call("writer", "echo", {"text": "x"})
        first = self.c.anchor_all()
        self.assertEqual([a["tenant"] for a in first], [T])
        self.assertEqual(self.c.anchor_all(), [])  # nothing new
        self.call("writer", "echo", {"text": "y"})
        self.assertEqual(len(self.c.anchor_all()), 1)

    def test_truncation_after_the_last_anchor_is_undetected_but_after_a_periodic_anchor_it_is(self):
        self.call("writer", "echo", {"text": "x"})
        self.c.anchor_all()
        for i in range(3):
            self.call("writer", "echo", {"text": str(i)})
        self.forge_tail(6)  # drops only events written after the anchor
        self.assertTrue(self.c.verify_all(T)["ok"])  # the documented window: nothing commits to those events yet
        # same attack once the periodic anchor has run: the tail is now covered
        d2 = Path(tempfile.mkdtemp())
        try:
            shutil.copy(self.d / "capabilities.json", d2 / "capabilities.json")
            c2 = Core(d2)
            c2.admin_principal("issue", T, "writer")
            for i in range(3):
                c2.ledger.append(T, "bench.event", "bench", {"i": i})
            c2.anchor_all()
            conn = sqlite3.connect(d2 / "atl.db")
            conn.execute("DROP TRIGGER events_no_delete")
            conn.execute("DELETE FROM events WHERE tenant_id=? AND seq > 2", (T,))
            conn.commit(); conn.close()
            r = c2.verify_all(T)
            self.assertFalse(r["ok"])
            self.assertIn("truncated", r["error"])
        finally:
            shutil.rmtree(d2, ignore_errors=True)


class TestSandboxScope(Base):
    def test_default_is_per_tenant_agents_share_files(self):
        self.assertTrue(self.call("writer", "fs_write", {"path": "secret.txt", "content": "s3cret"})["ok"])
        self.assertEqual(self.call("other", "fs_read", {"path": "secret.txt"})["result"]["content"], "s3cret")


class TestPerAgentSandbox(Base):
    manifest = {"per_agent_sandbox": True}

    def test_agents_do_not_see_each_others_files(self):
        self.assertTrue(self.call("writer", "fs_write", {"path": "secret.txt", "content": "s3cret"})["ok"])
        r = self.call("other", "fs_read", {"path": "secret.txt"})
        self.assertFalse(r["ok"])
        self.assertTrue(self.call("writer", "fs_read", {"path": "secret.txt"})["ok"])
        self.assertTrue((self.d / "sandbox" / T / "agent-writer" / "secret.txt").exists())

    def test_manifest_flag_must_be_boolean(self):
        doc = json.loads((ROOT / "capabilities.json").read_text())
        doc["limits"]["per_agent_sandbox"] = "yes"
        with self.assertRaises(PolicyError):
            Policy(doc)


class TestIds(unittest.TestCase):
    def test_dot_only_ids_are_rejected(self):
        for bad in (".", "..", "...", ""):
            self.assertFalse(valid_id(bad), bad)
        for ok in ("acme", "a.b", "a-b_c", ".hidden", "v1.2"):
            self.assertTrue(valid_id(ok), ok)

    def test_a_tenant_named_dotdot_cannot_be_created(self):
        d = Path(tempfile.mkdtemp())
        try:
            shutil.copy(ROOT / "capabilities.json", d / "capabilities.json")
            c = Core(d)
            with self.assertRaises(Exception):
                c.admin_principal("issue", "..", "writer")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
