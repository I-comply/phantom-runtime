import json, shutil, sqlite3, sys, tempfile, threading, unittest, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.gateway import Core
from atl.sidecar import Sidecar
from atl.util import sha256

ROOT = Path(__file__).resolve().parent.parent
T = "acme"


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers["Content-Length"])
        self.rfile.read(n)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"pong")

    def log_message(self, *a):
        pass


class TestSidecar(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "capabilities.json", self.d / "capabilities.json")
        self.c = Core(self.d)
        self.c.admin_principal("issue", T, "writer")  # creates the tenant
        self.sc = Sidecar(self.c.ledger, self.c.evidence, T)

    def tearDown(self):
        self.sc.uninstall_http()
        shutil.rmtree(self.d, ignore_errors=True)

    def types(self):
        return [e for e in self.c.ledger.events(T) if e["type"].startswith("audit.")]

    def test_http_recorded_without_secrets(self):
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.sc.install_http()
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/x?token=SECRET", data=b"hello",
                                     headers={"Authorization": "Bearer SECRET"})
        self.assertEqual(urllib.request.urlopen(req).read(), b"pong")
        srv.shutdown()
        ev = self.types()
        self.assertEqual([e["type"] for e in ev], ["audit.http.intent", "audit.http.result"])
        self.assertEqual(ev[0]["payload"]["body_sha256"], sha256(b"hello"))
        self.assertEqual(ev[1]["payload"]["response_sha256"], sha256(b"pong"))
        self.assertEqual(ev[1]["causation_id"], ev[0]["event_id"])
        self.assertNotIn("SECRET", json.dumps(ev))
        self.assertTrue(self.c.verify_all(T)["ok"])

    def test_fail_closed_when_ledger_down(self):
        self.sc.install_http()
        self.sc.ledger = type("L", (), {"append": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))})()
        with self.assertRaises(RuntimeError):
            urllib.request.urlopen("http://127.0.0.1:9/x", timeout=1)  # never reaches the network

    def test_db_recorded_and_params_hashed(self):
        db = self.sc.wrap_db(sqlite3.connect(":memory:"))
        db.execute("CREATE TABLE t(a)")
        db.execute("INSERT INTO t VALUES(?)", ("pii-value",))
        db.commit()
        self.assertEqual(db.execute("SELECT a FROM t").fetchall(), [("pii-value",)])
        ev = self.types()
        self.assertEqual(len(ev), 8)
        self.assertNotIn("pii-value", json.dumps(ev))
        self.assertEqual(ev[2]["payload"]["statement_sha256"], sha256("INSERT INTO t VALUES(?)"))
        self.assertTrue(self.c.verify_all(T)["ok"])

    def test_db_error_recorded_and_reraised(self):
        db = self.sc.wrap_db(sqlite3.connect(":memory:"))
        with self.assertRaises(sqlite3.OperationalError):
            db.execute("SELECT * FROM nope")
        self.assertEqual(self.types()[-1]["payload"], {"error": "OperationalError"})

    def test_store_bodies(self):
        sc = Sidecar(self.c.ledger, self.c.evidence, T, store_bodies=True)
        db = sc.wrap_db(sqlite3.connect(":memory:"))
        db.execute("SELECT 1")
        h = self.types()[0]["evidence"][0]
        self.assertEqual(self.c.evidence.get(T, h), b"SELECT 1")


if __name__ == "__main__":
    unittest.main()
