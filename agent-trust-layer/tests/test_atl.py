import json, shutil, sqlite3, sys, tempfile, threading, unittest, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.gateway import Core
from atl.policy import Policy, PolicyError
from atl.client import sign_request, sign_approval
from atl.util import now_ms, canon
from atl.ledger import verify_conn

ROOT = Path(__file__).resolve().parent.parent
T = "acme"


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "capabilities.json", self.d / "capabilities.json")
        self.c = Core(self.d)
        self.w = self.c.admin_principal("issue", T, "writer")
        self.r = self.c.admin_principal("issue", T, "reader")
        self.ap = self.c.admin_principal("issue", T, "alice", "approver")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def call(self, who, action, params, **kw):
        p = self.w if who == "writer" else self.r
        return self.c.invoke(sign_request(p["secret"], T, who, p["key_version"], action, params, **kw))


class TestCore(Base):
    def test_allow_and_chain(self):
        r = self.call("reader", "echo", {"text": "hi"})
        self.assertTrue(r["ok"]); self.assertEqual(r["result"], {"text": "hi"})
        v = self.c.verify_all(T)
        self.assertTrue(v["ok"]); self.assertGreaterEqual(v["count"], 6)
        types = [e["type"] for e in self.c.ledger.events(T)]
        self.assertEqual(types[-3:], ["authz.decision", "tool.invoked", "tool.completed"])

    def test_event_schema_and_causation(self):
        self.call("reader", "echo", {"text": "hi"})
        ev = self.c.ledger.events(T)[-3:]
        self.assertEqual(len({e["correlation_id"] for e in ev}), 1)
        self.assertEqual(ev[1]["causation_id"], ev[0]["event_id"])
        self.assertEqual(ev[2]["causation_id"], ev[1]["event_id"])

    def test_deny_not_granted_and_unknown(self):
        self.assertEqual(self.call("reader", "fs_write", {"path": "a", "content": "b"})["reason"], "not_granted")
        self.assertEqual(self.call("reader", "rm_rf", {})["reason"], "unknown_tool")

    def test_param_validation(self):
        self.assertTrue(self.call("reader", "echo", {"text": 5})["reason"].startswith("bad_type"))
        self.assertTrue(self.call("reader", "echo", {"text": "x", "z": 1})["reason"].startswith("unknown_param"))
        self.assertTrue(self.call("reader", "echo", {})["reason"].startswith("missing_param"))

    def test_bad_signature_and_unknown_agent_same_error(self):
        q = sign_request(self.r["secret"], T, "reader", 1, "echo", {"text": "x"}); q["signature"] = "0" * 64
        a = self.c.invoke(q)
        q2 = sign_request("00" * 32, T, "ghost", 1, "echo", {"text": "x"})
        b = self.c.invoke(q2)
        self.assertEqual((a["status"], a["error"]), (b["status"], b["error"]))
        self.assertEqual(self.c.ledger.events(T, 1000)[-1]["type"], "identity.issue")  # no ledger flooding

    def test_replay_rejected(self):
        q = sign_request(self.r["secret"], T, "reader", 1, "echo", {"text": "x"})
        self.assertTrue(self.c.invoke(q)["ok"])
        self.assertEqual(self.c.invoke(q)["status"], 401)

    def test_stale_timestamp(self):
        q = sign_request(self.r["secret"], T, "reader", 1, "echo", {"text": "x"}, ts=now_ms() - 10 * 60000)
        self.assertEqual(self.c.invoke(q)["status"], 401)

    def test_revocation_and_rotation(self):
        s2 = self.c.admin_principal("rotate", T, "reader")
        self.assertEqual(self.call("reader", "echo", {"text": "x"})["status"], 401)  # old key dead
        ok = self.c.invoke(sign_request(s2["secret"], T, "reader", 2, "echo", {"text": "x"}))
        self.assertTrue(ok["ok"])
        self.c.admin_principal("revoke", T, "reader")
        self.assertEqual(self.c.invoke(sign_request(s2["secret"], T, "reader", 2, "echo", {"text": "x"}))["status"], 401)
        self.assertIn("identity.rejected", [e["type"] for e in self.c.ledger.events(T, 1000)])

    def test_expiry(self):
        e = self.c.admin_principal("issue", T, "short", ttl_days=-1)
        self.assertEqual(self.c.invoke(sign_request(e["secret"], T, "short", 1, "echo", {"text": "x"}))["status"], 401)

    def test_destructive_needs_approval_bound_to_intent(self):
        self.call("writer", "fs_write", {"path": "a.txt", "content": "x"})
        p = {"path": "a.txt"}
        r = self.call("writer", "fs_delete", p)
        self.assertEqual(r["decision"], "needs_approval")
        ap = sign_approval(self.ap["secret"], T, "alice", 1, "writer", "fs_delete", p, now_ms() + 60000)
        other = self.call("writer", "fs_delete", {"path": "b.txt"}, approval=ap)
        self.assertEqual(other["reason"], "approval_invalid")  # bound to different params
        good = self.call("writer", "fs_delete", p, approval=ap)
        self.assertTrue(good["ok"])
        self.assertEqual(self.call("writer", "fs_delete", p, approval=ap)["reason"], "approval_already_used")

    def test_approval_expiry_and_self_approval(self):
        p = {"path": "a.txt"}
        old = sign_approval(self.ap["secret"], T, "alice", 1, "writer", "fs_delete", p, now_ms() - 1000)
        self.assertEqual(self.call("writer", "fs_delete", p, approval=old)["reason"], "approval_expired_or_too_long")
        long = sign_approval(self.ap["secret"], T, "alice", 1, "writer", "fs_delete", p, now_ms() + 10 * 3600000)
        self.assertEqual(self.call("writer", "fs_delete", p, approval=long)["reason"], "approval_expired_or_too_long")
        self.c.admin_principal("issue", T, "writer", "approver")
        me = self.c.ident.derive(T, "writer", "approver", 1).hex()
        mine = sign_approval(me, T, "writer", 1, "writer", "fs_delete", p, now_ms() + 60000)
        self.assertEqual(self.call("writer", "fs_delete", p, approval=mine)["reason"], "self_approval")

    def test_agent_key_cannot_approve(self):
        p = {"path": "a.txt"}
        forged = sign_approval(self.w["secret"], T, "alice", 1, "writer", "fs_delete", p, now_ms() + 60000)
        self.assertEqual(self.call("writer", "fs_delete", p, approval=forged)["reason"], "approval_invalid")

    def test_tenant_isolation(self):
        o = self.c.admin_principal("issue", "other", "reader")
        self.assertTrue(self.c.invoke(sign_request(o["secret"], "other", "reader", 1, "echo", {"text": "x"}))["ok"])
        self.assertEqual(self.c.invoke(sign_request(o["secret"], T, "reader", 1, "echo", {"text": "x"}))["status"], 401)
        self.assertTrue(all(e["tenant_id"] == "other" for e in self.c.ledger.events("other", 1000)))
        self.assertTrue(self.c.verify_all("other")["ok"] and self.c.verify_all(T)["ok"])
        h = self.c.ledger.events("other", 1000)[-1]["evidence"][0]
        self.assertFalse(self.c.evidence.check(T, h))

    def test_idempotency(self):
        a = self.call("writer", "fs_write", {"path": "i.txt", "content": "1"}, idempotency_key="k1")
        b = self.call("writer", "fs_write", {"path": "i.txt", "content": "1"}, idempotency_key="k1")
        self.assertTrue(b["replayed"]); self.assertEqual(a["correlation_id"], b["correlation_id"])
        self.assertEqual(sum(e["type"] == "tool.invoked" for e in self.c.ledger.events(T, 1000)), 1)
        c = self.call("writer", "fs_write", {"path": "i.txt", "content": "2"}, idempotency_key="k1")
        self.assertEqual(c["error"], "idempotency_key_reuse")

    def test_sandbox_path_escape(self):
        for pth in ("../x", "/etc/passwd", "a/../../x"):
            r = self.call("writer", "fs_write", {"path": pth, "content": "x"})
            self.assertFalse(r["ok"]); self.assertIn("path_escape", r["error"])
        (self.d / "sandbox" / T).mkdir(parents=True, exist_ok=True)
        (self.d / "sandbox" / T / "link").symlink_to("/etc")
        r = self.call("reader", "fs_read", {"path": "link/passwd"})
        self.assertFalse(r["ok"]); self.assertIn("path_escape", r["error"])

    def test_malformed_payloads(self):
        q = sign_request(self.r["secret"], T, "reader", 1, "echo", {"text": "x"}); q["params"] = {"text": float("nan")}
        self.assertEqual(self.c.invoke(q)["status"], 400)
        q["params"] = {"a": {"b": {}}}
        deep = {}
        cur = deep
        for _ in range(40):
            cur["x"] = {}; cur = cur["x"]
        q["params"] = deep
        self.assertEqual(self.c.invoke(q)["status"], 400)
        self.assertEqual(self.c.invoke("nope")["status"], 400)

    def test_pre_auth_rate_limit_does_not_lock_victim(self):
        for _ in range(35):
            q = sign_request(self.r["secret"], T, "reader", 1, "echo", {"text": "x"}); q["signature"] = "0" * 64
            self.c.invoke(q, src="9.9.9.9")
        self.assertEqual(self.call("reader", "echo", {"text": "x"})["status"], 200)  # other source unaffected
        q = sign_request(self.r["secret"], T, "reader", 1, "echo", {"text": "x"})
        self.assertEqual(self.c.invoke(q, src="9.9.9.9")["status"], 429)

    def test_worker_timeout(self):
        r = self.c.executor.run("echo", {"text": "x"}, 0.0001)
        self.assertFalse(r["ok"])


class TestLedger(Base):
    def test_append_only_triggers(self):
        self.call("reader", "echo", {"text": "x"})
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.conn().execute("UPDATE events SET type='x'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.conn().execute("DELETE FROM events")

    def _bypass(self, sql):
        c = self.c.db.conn()
        c.executescript("DROP TRIGGER events_no_update; DROP TRIGGER events_no_delete;")
        c.execute(sql)

    def test_tamper_content(self):
        self.call("reader", "echo", {"text": "x"})
        self._bypass("UPDATE events SET payload='{\"x\":1}' WHERE seq=2")
        v = self.c.verify_all(T)
        self.assertFalse(v["ok"]); self.assertIn("seq 2", v["error"])

    def test_tamper_rehash_needs_key(self):
        from atl.util import sha256
        from atl.ledger import _body
        self.call("reader", "echo", {"text": "x"})
        self._bypass("UPDATE events SET payload='{\"x\":1}' WHERE seq=3")
        conn = self.c.db.conn()
        # attacker without MAC key recomputes hashes down the chain
        prev = None
        for r in conn.execute("SELECT * FROM events WHERE tenant_id=? ORDER BY seq", (T,)).fetchall():
            b = _body(r)
            if prev:
                b["prev_hash"] = prev
            h = sha256(canon(b))
            conn.execute("UPDATE events SET prev_hash=?,hash=? WHERE tenant_id=? AND seq=?", (b["prev_hash"], h, T, r["seq"]))
            prev = h
        self.assertTrue(verify_conn(conn, T)["ok"])  # chain-only passes
        v = self.c.verify_all(T)
        self.assertFalse(v["ok"]); self.assertIn("mac mismatch", v["error"])

    def test_delete_and_truncate(self):
        self.call("reader", "echo", {"text": "x"})
        self.c.anchor(T)
        self._bypass("DELETE FROM events WHERE seq>4")
        v = self.c.verify_all(T)
        self.assertFalse(v["ok"]); self.assertIn("truncated", v["error"])

    def test_delete_middle_gap(self):
        self.call("reader", "echo", {"text": "x"})
        self._bypass("DELETE FROM events WHERE seq=3")
        self.assertIn("gap", self.c.verify_all(T)["error"])

    def test_evidence_corruption(self):
        self.call("reader", "echo", {"text": "x"})
        h = self.c.ledger.events(T, 1000)[-1]["evidence"][0]
        (self.d / "evidence" / T / h[:2] / h).write_bytes(b"corrupt")
        self.assertIn("evidence", self.c.verify_all(T)["error"])

    def test_concurrent_appends_stay_linear(self):
        def w():
            for _ in range(10):
                self.c.ledger.append(T, "x", "t", {"n": 1})
        th = [threading.Thread(target=w) for _ in range(5)]
        [t.start() for t in th]; [t.join() for t in th]
        v = self.c.verify_all(T)
        self.assertTrue(v["ok"]); self.assertGreaterEqual(v["count"], 50)


class TestPolicy(unittest.TestCase):
    def test_fail_closed_on_bad_manifest(self):
        for bad in ({}, {"version": 2}, {"version": 1, "tools": {"x": {"risk": "meh"}}, "grants": {}},
                    {"version": 1, "tools": {}, "grants": {"*": "echo"}}):
            with self.assertRaises(PolicyError):
                Policy(bad)
        d = Path(tempfile.mkdtemp()); (d / "capabilities.json").write_text("{not json")
        with self.assertRaises(Exception):
            Core(d)
        shutil.rmtree(d, ignore_errors=True)


class TestHTTP(Base):
    def test_http_flow(self):
        from atl.server import make_handler
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.c, "tok"))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def post(path, body, h=None):
            r = urllib.request.Request(base + path, json.dumps(body).encode(), dict({"Content-Type": "application/json"}, **(h or {})))
            try:
                with urllib.request.urlopen(r) as f:
                    return f.status, json.loads(f.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        s, b = post("/v1/invoke", sign_request(self.r["secret"], T, "reader", 1, "hash_text", {"text": "abc"}))
        self.assertEqual(s, 200)
        self.assertEqual(b["result"]["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(post("/v1/admin/anchor", {"tenant_id": T})[0], 401)
        self.assertEqual(post("/v1/admin/anchor", {"tenant_id": T}, {"X-ATL-Admin": "tok"})[0], 200)
        self.assertEqual(post("/v1/invoke", {"junk": 1})[0], 400)
        srv.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=1)
