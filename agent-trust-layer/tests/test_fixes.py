"""Gaps found by running ATL: abandoned idempotent requests, forgeable chain-only verification,
erasure vs evidence, policy value constraints, per-tool budgets, anchor publication, admin read logging."""
import io, json, os, shutil, sqlite3, sys, tempfile, threading, unittest, urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atl.client, atl.gateway
from atl import cli
from atl.gateway import Core
from atl.policy import Policy, PolicyError
from atl.client import sign_request
from atl.ledger import verify_conn, _body
from atl.server import make_handler
from atl.util import canon, sha256, now_ms

ROOT = Path(__file__).resolve().parent.parent
T = "acme"


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "capabilities.json", self.d / "capabilities.json")
        self.c = Core(self.d)
        self.w = self.c.admin_principal("issue", T, "writer")
        self.r = self.c.admin_principal("issue", T, "reader")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def call(self, who, action, params, **kw):
        p = self.w if who == "writer" else self.r
        return self.c.invoke(sign_request(p["secret"], T, who, p["key_version"], action, params, **kw))

    def types(self):
        return [e["type"] for e in self.c.ledger.events(T, 1000)]


class TestAbandonedRequests(Base):
    def crash_mid_execution(self, key):
        with mock.patch.object(self.c.executor, "run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.call("reader", "echo", {"text": "x"}, idempotency_key=key)

    def later(self, ms):
        t = now_ms() + ms
        return mock.patch.object(atl.gateway, "now_ms", lambda: t), mock.patch.object(atl.client, "now_ms", lambda: t)

    def test_stuck_key_gets_a_terminal_answer_after_the_lease(self):
        self.crash_mid_execution("k1")
        self.assertEqual(self.call("reader", "echo", {"text": "x"}, idempotency_key="k1")["error"], "in_progress")
        lease_ms = self.c.policy.limits["idem_lease_s"] * 1000
        a, b = self.later(lease_ms + 1000)
        with a, b:
            r = self.call("reader", "echo", {"text": "x"}, idempotency_key="k1")
            self.assertEqual((r["status"], r["error"]), (409, "abandoned"))
            self.assertEqual(r["executed"], "unknown")  # tool.invoked was recorded, no outcome
            again = self.call("reader", "echo", {"text": "x"}, idempotency_key="k1")
            self.assertTrue(again.get("replayed"))
            self.assertEqual(again["error"], "abandoned")
            self.assertTrue(self.call("reader", "echo", {"text": "y"}, idempotency_key="k2")["ok"])  # fresh key works
        self.assertEqual(self.types().count("tool.abandoned"), 1)
        self.assertTrue(self.c.verify_all(T)["ok"])

    def test_abandoned_before_invocation_says_not_executed(self):
        with mock.patch.object(self.c.ledger, "append", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.call("reader", "echo", {"text": "x"}, idempotency_key="k3")
        a, b = self.later(self.c.policy.limits["idem_lease_s"] * 1000 + 1000)
        with a, b:
            r = self.call("reader", "echo", {"text": "x"}, idempotency_key="k3")
        self.assertEqual((r["error"], r["executed"]), ("abandoned", "no"))

    def test_recovers_completed_outcome_when_only_the_response_write_was_lost(self):
        ok = self.call("reader", "echo", {"text": "hello"}, idempotency_key="k4")
        self.assertTrue(ok["ok"])
        self.c.db.conn().execute("UPDATE requests SET response=NULL, started=? WHERE idem_key='k4'", (now_ms() - 10 ** 7,))
        r = self.call("reader", "echo", {"text": "hello"}, idempotency_key="k4")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"], {"text": "hello"})
        self.assertEqual(self.types().count("tool.invoked"), 1)  # not executed a second time

    def test_in_progress_inside_the_lease_is_unchanged(self):
        self.c.db.conn().execute("INSERT INTO requests VALUES(?,?,?,NULL,?)",
                                 (T, "k5", atl.client.intent_digest(T, "reader", "echo", {"text": "x"}), now_ms()))
        self.assertEqual(self.call("reader", "echo", {"text": "x"}, idempotency_key="k5")["error"], "in_progress")

    def test_idempotency_key_reuse_with_different_params_still_rejected(self):
        self.assertTrue(self.call("reader", "echo", {"text": "x"}, idempotency_key="k6")["ok"])
        self.assertEqual(self.call("reader", "echo", {"text": "z"}, idempotency_key="k6")["error"], "idempotency_key_reuse")

    def test_existing_database_without_started_column_is_migrated(self):
        d = Path(tempfile.mkdtemp())
        try:
            shutil.copy(ROOT / "capabilities.json", d / "capabilities.json")
            conn = sqlite3.connect(d / "atl.db")
            conn.execute("CREATE TABLE requests(tenant_id TEXT NOT NULL, idem_key TEXT NOT NULL, digest TEXT NOT NULL, response TEXT, PRIMARY KEY(tenant_id, idem_key))")
            conn.commit(); conn.close()
            c = Core(d)
            self.assertIn("started", [r["name"] for r in c.db.conn().execute("PRAGMA table_info(requests)")])
        finally:
            shutil.rmtree(d, ignore_errors=True)


def forge(db_path, tenant, seq, new_payload):
    """What an attacker with DB write access can do: rewrite one event and recompute every later hash."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("DROP TRIGGER events_no_update")
    conn.execute("UPDATE events SET payload=? WHERE tenant_id=? AND seq=?", (canon(new_payload), tenant, seq))
    prev = conn.execute("SELECT hash FROM events WHERE tenant_id=? AND seq=?", (tenant, seq - 1)).fetchone()["hash"]
    for r in conn.execute("SELECT * FROM events WHERE tenant_id=? AND seq>=? ORDER BY seq", (tenant, seq)).fetchall():
        conn.execute("UPDATE events SET prev_hash=? WHERE tenant_id=? AND seq=?", (prev, tenant, r["seq"]))
        r = conn.execute("SELECT * FROM events WHERE tenant_id=? AND seq=?", (tenant, r["seq"])).fetchone()
        prev = sha256(canon(_body(r)))
        conn.execute("UPDATE events SET hash=? WHERE tenant_id=? AND seq=?", (prev, tenant, r["seq"]))
    conn.commit(); conn.close()


class TestChainOnlyVerification(Base):
    def setUp(self):
        super().setUp()
        for i in range(3):
            self.call("reader", "echo", {"text": str(i)})
        self.c.anchor(T)
        self.external = self.d / "external-anchors.jsonl"
        shutil.copy(self.d / "anchors.jsonl", self.external)  # what an auditor receives out of band
        self.db = self.d / "atl.db"

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ex:
            cli.main(["--dir", str(self.d), "verify", T, "--chain-only", *args])
        return ex.exception.code, json.loads(out.getvalue())

    def test_chain_only_alone_is_forgeable_and_says_so(self):
        forge(self.db, T, 2, {"forged": True})
        code, out = self.run_cli()
        self.assertEqual(code, 0)  # the documented limitation, now stated in the output
        self.assertEqual(out["assurance"], "structure_only")
        self.assertIn("recompute", out["warning"])

    def test_chain_only_with_externally_held_anchors_catches_the_forgery(self):
        forge(self.db, T, 2, {"forged": True})
        code, out = self.run_cli("--anchors", str(self.external))
        self.assertEqual(code, 1)
        self.assertIn("diverges from anchor", out["error"])

    def test_chain_only_with_anchors_passes_on_an_untouched_ledger(self):
        code, out = self.run_cli("--anchors", str(self.external))
        self.assertEqual((code, out["assurance"]), (0, "structure_and_anchors"))

    def test_keyed_verification_still_catches_it(self):
        forge(self.db, T, 2, {"forged": True})
        self.assertFalse(self.c.verify_all(T)["ok"])


class TestEvidenceErasure(Base):
    def setUp(self):
        super().setUp()
        self.call("writer", "fs_write", {"path": "p.txt", "content": "alice@example.com ssn 123-45-6789"})
        ev = [e for e in self.c.ledger.events(T, 1000) if e["type"] == "authz.decision"][-1]
        self.h = ev["evidence"][0]

    def test_erasure_removes_the_blob_and_keeps_the_ledger_verifiable(self):
        self.assertIn(b"ssn", self.c.evidence.get(T, self.h))
        r = self.c.erase_evidence(T, self.h, "subject request 42")
        self.assertEqual(r["erased"], self.h)
        with self.assertRaises(OSError):
            self.c.evidence.get(T, self.h)
        self.assertEqual(self.types()[-1], "evidence.erased")
        self.assertTrue(self.c.verify_all(T)["ok"])
        self.assertTrue(self.c.verify_all(T)["ok"])  # still, after the blob is gone

    def test_erasure_is_idempotent(self):
        self.c.erase_evidence(T, self.h, "r")
        n = len(self.c.ledger.events(T, 1000))
        self.assertTrue(self.c.erase_evidence(T, self.h, "r")["already"])
        self.assertEqual(len(self.c.ledger.events(T, 1000)), n)

    def test_cannot_erase_a_hash_the_ledger_does_not_reference(self):
        with self.assertRaises(ValueError):
            self.c.erase_evidence(T, "0" * 64, "r")
        with self.assertRaises(ValueError):
            self.c.erase_evidence(T, "../../etc/passwd", "r")

    def test_corruption_or_deletion_without_a_tombstone_is_still_detected(self):
        p = self.d / "evidence" / T / self.h[:2] / self.h
        p.unlink()
        self.assertFalse(self.c.verify_all(T)["ok"])

    def test_erasing_in_one_tenant_does_not_touch_another(self):
        o = self.c.admin_principal("issue", "other", "reader")
        self.c.invoke(sign_request(o["secret"], "other", "reader", 1, "echo", {"text": "x"}))
        other_h = [e for e in self.c.ledger.events("other", 1000) if e["evidence"]][0]["evidence"][0]
        with self.assertRaises(ValueError):
            self.c.erase_evidence(T, other_h, "r")  # not referenced by T's ledger
        self.assertTrue(self.c.verify_all("other")["ok"])


class TestPolicyConstraints(unittest.TestCase):
    def policy(self, params, **tool):
        return Policy({"version": 1, "tools": {"t": dict({"risk": "low", "params": params}, **tool)}, "grants": {"*": ["t"]}})

    def test_enum_pattern_and_range(self):
        p = self.policy({"mode": {"type": "string", "enum": ["a", "b"], "required": True},
                         "path": {"type": "string", "pattern": r"workspace/([a-z0-9_-]+/)*[a-z0-9_-]+(\.[a-z0-9]+)?", "max": 100},
                         "n": {"type": "integer", "min": 1, "max": 10}})
        ok = {"mode": "a", "path": "workspace/x.txt", "n": 5}
        self.assertEqual(p.decide("x", "t", ok)["decision"], "allow")
        self.assertEqual(p.decide("x", "t", dict(ok, mode="c"))["reason"], "not_in_enum:mode")
        self.assertEqual(p.decide("x", "t", dict(ok, path="../etc/passwd"))["reason"], "pattern_mismatch:path")
        self.assertEqual(p.decide("x", "t", dict(ok, path="workspace/../../etc"))["decision"], "deny")
        self.assertEqual(p.decide("x", "t", dict(ok, n=0))["reason"], "out_of_range:n")
        self.assertEqual(p.decide("x", "t", dict(ok, n=11))["reason"], "out_of_range:n")

    def test_pattern_must_match_the_whole_value(self):
        p = self.policy({"path": {"type": "string", "pattern": r"workspace/[a-z]+"}})
        self.assertEqual(p.decide("x", "t", {"path": "workspace/abc/../../x"})["reason"], "pattern_mismatch:path")

    def test_bad_constraints_fail_closed_at_load(self):
        for bad in ({"type": "string", "pattern": "(unclosed"}, {"type": "string", "enum": "notalist"},
                    {"type": "string", "min": 1}, {"type": "integer", "min": "x"}, {"type": "integer", "enum": ["a"]},
                    {"type": "integer", "min": 5, "max": 1}):
            with self.assertRaises(PolicyError, msg=bad):
                self.policy({"p": bad})
        with self.assertRaises(PolicyError):
            self.policy({"p": {"type": "string"}}, rate_per_minute=0)


class TestToolBudget(Base):
    def test_per_tool_rate_limit(self):
        doc = json.loads((ROOT / "capabilities.json").read_text())
        doc["tools"]["echo"]["rate_per_minute"] = 2
        (self.d / "capabilities.json").write_text(json.dumps(doc))
        c = Core(self.d)
        r = c.admin_principal("issue", "t2", "bob")
        res = [c.invoke(sign_request(r["secret"], "t2", "bob", 1, "echo", {"text": "x"})) for _ in range(4)]
        self.assertEqual([x["ok"] for x in res], [True, True, False, False])
        self.assertEqual(res[2]["reason"], "tool_rate_limited")
        self.assertEqual(c.invoke(sign_request(r["secret"], "t2", "bob", 1, "hash_text", {"text": "x"}))["ok"], True)


class TestAnchorsAndAdminReads(Base):
    def test_anchor_publication_result_is_recorded_in_the_ledger(self):
        self.call("reader", "echo", {"text": "x"})
        with mock.patch.dict(os.environ, {"ATL_ANCHOR_WEBHOOK": "http://127.0.0.1:1/hook"}):
            a = self.c.anchor(T)
        self.assertTrue(a["webhook"].startswith("failed:"))
        ev = [e for e in self.c.ledger.events(T, 1000) if e["type"] == "anchor.published"][-1]
        self.assertEqual((ev["payload"]["seq"], ev["payload"]["hash"]), (a["seq"], a["hash"]))
        self.assertTrue(ev["payload"]["webhook"].startswith("failed:"))
        self.assertTrue(self.c.verify_all(T)["ok"])

    def test_anchor_file_can_live_outside_the_data_dir(self):
        ext = Path(tempfile.mkdtemp())
        try:
            with mock.patch.dict(os.environ, {"ATL_ANCHOR_FILE": str(ext / "a.jsonl")}):
                c = Core(self.d)
                self.call("reader", "echo", {"text": "x"})
                c.anchor(T)
            self.assertTrue((ext / "a.jsonl").exists())
            self.assertFalse((self.d / "anchors.jsonl").exists())
        finally:
            shutil.rmtree(ext, ignore_errors=True)

    def test_admin_reads_and_verifies_are_recorded(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.c, "tok"))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def get(path):
                r = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", headers={"X-ATL-Admin": "tok"})
                with urllib.request.urlopen(r) as f:
                    return json.loads(f.read())
            self.assertTrue(get(f"/v1/admin/verify?tenant_id={T}")["ok"])
            get(f"/v1/admin/events?tenant_id={T}&limit=5")
        finally:
            srv.shutdown(); srv.server_close()
        reads = [e for e in self.c.ledger.events(T, 1000) if e["type"] == "admin.read"]
        self.assertEqual([e["payload"]["endpoint"] for e in reads], ["verify", "events"])
        self.assertTrue(self.c.verify_all(T)["ok"])


if __name__ == "__main__":
    unittest.main()
