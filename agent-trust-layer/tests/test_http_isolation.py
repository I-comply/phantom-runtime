import json, shutil, sys, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.gateway import Core
from atl.server import make_handler
from atl.client import sign_request

ROOT = Path(__file__).resolve().parent.parent


class TestHTTPIsolation(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "capabilities.json", self.d / "capabilities.json")
        self.c = Core(self.d)
        self.p = {t: self.c.admin_principal("issue", t, "writer") for t in ("alpha", "beta")}
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.c, "tok"))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
        shutil.rmtree(self.d, ignore_errors=True)

    def req(self, method, path, body=None, admin=True):
        h = {"Content-Type": "application/json"}
        if admin:
            h["X-ATL-Admin"] = "tok"
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None, h, method=method)
        try:
            with urllib.request.urlopen(r) as f:
                return f.status, json.loads(f.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def invoke(self, t, action, params, secret_of=None):
        s = self.p[secret_of or t]["secret"]
        return self.req("POST", "/v1/invoke", sign_request(s, t, "writer", 1, action, params), admin=False)

    def test_cross_tenant_credentials_rejected(self):
        self.assertEqual(self.invoke("alpha", "echo", {"text": "x"})[0], 200)
        s, b = self.invoke("alpha", "echo", {"text": "x"}, secret_of="beta")
        self.assertEqual((s, b["error"]), (401, "unauthorized"))

    def test_files_not_shared_between_tenants(self):
        self.assertEqual(self.invoke("alpha", "fs_write", {"path": "secret.txt", "content": "alpha-data"})[0], 200)
        s, b = self.invoke("beta", "fs_read", {"path": "secret.txt"})
        self.assertNotEqual(s, 200)
        self.assertNotIn("alpha-data", json.dumps(b))
        s, b = self.invoke("beta", "fs_read", {"path": "../alpha/secret.txt"})
        self.assertNotEqual(s, 200); self.assertIn("path_escape", b["error"])

    def test_ledger_and_evidence_scoped_over_http(self):
        self.invoke("alpha", "echo", {"text": "alpha-only"})
        s, b = self.req("GET", "/v1/admin/events?tenant_id=beta")
        self.assertEqual(s, 200)
        self.assertTrue(all(e["tenant_id"] == "beta" for e in b["events"]))
        self.assertNotIn("alpha-only", json.dumps(b))
        for t in ("alpha", "beta"):
            self.assertTrue(self.req("GET", f"/v1/admin/verify?tenant_id={t}")[1]["ok"])

    def test_admin_endpoints_require_token(self):
        for m, p in (("GET", "/v1/admin/events?tenant_id=alpha"), ("GET", "/v1/admin/verify?tenant_id=alpha"),
                     ("POST", "/v1/admin/anchor"), ("POST", "/v1/admin/principals")):
            s, _ = self.req(m, p, {} if m == "POST" else None, admin=False)
            self.assertEqual(s, 401, p)

    def test_replay_and_idempotency_are_per_tenant(self):
        q = sign_request(self.p["alpha"]["secret"], "alpha", "writer", 1, "echo", {"text": "x"}, nonce="n" * 16)
        self.assertEqual(self.req("POST", "/v1/invoke", q, admin=False)[0], 200)
        self.assertEqual(self.req("POST", "/v1/invoke", q, admin=False)[0], 401)
        for t in ("alpha", "beta"):  # same idempotency key in two tenants must not collide
            s = self.p[t]["secret"]
            r = self.req("POST", "/v1/invoke", sign_request(s, t, "writer", 1, "echo", {"text": t}, idempotency_key="same"), admin=False)
            self.assertEqual((r[0], r[1].get("replayed")), (200, None))

    def test_invalid_tenant_id_rejected(self):
        for t in ("../beta", "a/b", "x" * 80, ""):
            q = sign_request(self.p["alpha"]["secret"], t, "writer", 1, "echo", {"text": "x"})
            self.assertEqual(self.req("POST", "/v1/invoke", q, admin=False)[0], 400, t)


if __name__ == "__main__":
    unittest.main()
