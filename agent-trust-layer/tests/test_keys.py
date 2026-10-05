import base64, json, os, secrets, shutil, sqlite3, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.gateway import Core
from atl.client import sign_request
from atl.keys import (FileProvider, EnvProvider, AwsKmsProvider, VaultKVProvider, VaultTransitProvider,
                      KeyError_, make_provider)
from atl.ledger import verify_conn

ROOT = Path(__file__).resolve().parent.parent
T = "acme"


def mk(env=None):
    d = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "capabilities.json", d / "capabilities.json")
    return d


class FakeKMS:
    def __init__(self):
        self.k = secrets.token_bytes(32)

    def _x(self, b):
        return bytes(x ^ y for x, y in zip(b, self.k * 4))

    def generate_data_key(self, KeyId, KeySpec):
        p = secrets.token_bytes(32)
        return {"Plaintext": p, "CiphertextBlob": self._x(p)}

    def decrypt(self, CiphertextBlob, KeyId):
        return {"Plaintext": self._x(CiphertextBlob)}


class FakeVault(BaseHTTPRequestHandler):
    store = {}
    tkey = secrets.token_bytes(32)

    def log_message(self, *a):
        pass

    def _send(self, o):
        b = json.dumps(o).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def _auth(self):
        if self.headers.get("X-Vault-Token") != "tok":
            self.send_response(403); self.send_header("Content-Length", "0"); self.end_headers(); return False
        return True

    def do_GET(self):
        if not self._auth():
            return
        p = self.path
        if p in self.store:
            return self._send({"data": {"data": self.store[p]}})
        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def do_POST(self):
        if not self._auth():
            return
        b = self._body()
        if "/transit/datakey/plaintext/" in self.path:
            pt = secrets.token_bytes(32)
            ct = "vault:v1:" + base64.b64encode(bytes(x ^ y for x, y in zip(pt, self.tkey))).decode()
            return self._send({"data": {"plaintext": base64.b64encode(pt).decode(), "ciphertext": ct}})
        if "/transit/decrypt/" in self.path:
            ct = base64.b64decode(b["ciphertext"][len("vault:v1:"):])
            return self._send({"data": {"plaintext": base64.b64encode(bytes(x ^ y for x, y in zip(ct, self.tkey))).decode()}})
        self.store[self.path] = b["data"]
        self._send({})


class Rotation(unittest.TestCase):
    def setUp(self):
        self.d = mk()
        self.c = Core(self.d)
        self.old = self.c.admin_principal("issue", T, "writer")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def inv(self, p, who="writer"):
        return self.c.invoke(sign_request(p["secret"], T, who, p["key_version"], "echo", {"text": "x"}))

    def test_old_keys_and_events_verify_after_rotation(self):
        self.assertEqual(self.inv(self.old)["status"], 200)
        r = self.c.rotate_master()
        self.assertEqual(r["master_version"], 2)
        self.assertEqual(self.inv(self.old)["status"], 200)  # principal secret issued under v1 still works
        new = self.c.admin_principal("issue", T, "w2")
        self.assertNotEqual(new["secret"], self.old["secret"])
        self.assertEqual(self.inv(new, "w2")["status"], 200)
        ev = self.c.ledger.events(T, 1000)
        self.assertIn("key.rotated", [e["type"] for e in ev])
        rot = [e for e in ev if e["type"] == "key.rotated"][0]
        self.assertEqual(rot["payload"]["master_version"], 2)
        self.c.anchor(T)
        self.assertTrue(self.c.verify_all(T)["ok"])
        # rotated principal re-derives under the new master
        rp = self.c.admin_principal("rotate", T, "writer")
        self.assertEqual(self.inv(rp)["status"], 200)
        self.assertTrue(self.c.verify_all(T)["ok"])

    def test_old_anchor_verifies_after_rotation(self):
        self.inv(self.old)
        self.c.anchor(T)
        self.c.rotate_master()
        self.assertTrue(self.c.verify_all(T)["ok"])

    def test_new_tenant_after_rotation_starts_with_rotation_event(self):
        self.c.rotate_master()
        p = self.c.admin_principal("issue", "beta", "a")
        evs = self.c.ledger.events("beta", 10)
        self.assertEqual(evs[0]["type"], "key.rotated")
        self.assertEqual(evs[0]["payload"]["master_version"], 2)
        self.assertTrue(self.c.verify_all("beta")["ok"])

    def test_tamper_after_rotation_detected(self):
        self.c.rotate_master(); self.inv(self.old)
        conn = self.c.db.conn()
        conn.executescript("DROP TRIGGER events_no_update;")
        conn.execute("UPDATE events SET payload='{\"x\":1}' WHERE tenant_id=? AND seq=2", (T,))
        r = self.c.verify_all(T)
        self.assertFalse(r["ok"])

    def test_forged_rotation_or_downgrade_detected(self):
        self.c.rotate_master()
        conn = self.c.db.conn()
        conn.executescript("DROP TRIGGER events_no_update;")
        # rewrite the rotation event to claim a different version and fix the hash chain without the key
        from atl.util import canon, sha256
        row = conn.execute("SELECT * FROM events WHERE tenant_id=? AND type='key.rotated'", (T,)).fetchone()
        conn.execute("UPDATE events SET payload=? WHERE tenant_id=? AND seq=?",
                     (canon({"master_version": 1, "previous": 1}), T, row["seq"]))
        self.assertFalse(self.c.verify_all(T)["ok"])

    def test_missing_old_master_fails_verification(self):
        self.c.rotate_master(); self.inv(self.old)
        os.remove(self.d / "master.key")
        # FileProvider recreates v1 on open -> different key -> must not verify
        c2 = Core(self.d)
        self.assertFalse(c2.verify_all(T)["ok"])

    def test_chain_only_exit_code(self):
        self.c.rotate_master()
        import subprocess
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        ok = subprocess.run([sys.executable, "-m", "atl", "--dir", str(self.d), "verify", T], env=env, capture_output=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        conn = self.c.db.conn(); conn.executescript("DROP TRIGGER events_no_update;")
        conn.execute("UPDATE events SET payload='{\"x\":1}' WHERE tenant_id=? AND seq=2", (T,))
        bad = subprocess.run([sys.executable, "-m", "atl", "--dir", str(self.d), "verify", T], env=env, capture_output=True)
        self.assertEqual(bad.returncode, 1)
        bad = subprocess.run([sys.executable, "-m", "atl", "--dir", str(self.d), "verify", T, "--chain-only"], env=env, capture_output=True)
        self.assertEqual(bad.returncode, 1)


class Providers(unittest.TestCase):
    def tearDown(self):
        for k in [k for k in os.environ if k.startswith("ATL_")]:
            del os.environ[k]

    def all_disk_text(self, d):
        return b"".join(p.read_bytes() for p in Path(d).rglob("*") if p.is_file() and p.name != "atl.db")

    def test_env_provider_no_disk_and_versions(self):
        k1, k2 = secrets.token_hex(32), secrets.token_hex(32)
        os.environ.update(ATL_MASTER_KEY_HEX=k2, ATL_MASTER_KEY_VERSION="2", ATL_MASTER_KEY_HEX_V1=k1)
        p = EnvProvider()
        self.assertEqual((p.current_version(), p.get(1).hex(), p.get(2).hex()), (2, k1, k2))
        with self.assertRaises(KeyError_):
            p.get(3)
        with self.assertRaises(KeyError_):
            p.rotate()
        d = mk(); c = Core(d)
        c.admin_principal("issue", T, "a")
        self.assertFalse((d / "master.key").exists())
        blob = self.all_disk_text(d)
        self.assertNotIn(k1.encode(), blob); self.assertNotIn(k2.encode(), blob)

    def test_env_provider_selected_by_default_when_key_set(self):
        os.environ["ATL_MASTER_KEY_HEX"] = secrets.token_hex(32)
        self.assertEqual(make_provider(mk()).name, "env")
        os.environ["ATL_KEY_PROVIDER"] = "file"
        self.assertEqual(make_provider(mk()).name, "file")
        os.environ["ATL_KEY_PROVIDER"] = "nope"
        with self.assertRaises(KeyError_):
            make_provider(mk())

    def test_aws_kms_envelope_memory_only_and_rotation(self):
        kms = FakeKMS(); d = mk()
        p = AwsKmsProvider(d, client=kms, key_id="k")
        plain1 = p.get(1)
        self.assertEqual(p.rotate(), 2)
        p2 = AwsKmsProvider(d, client=kms, key_id="k")  # fresh process: unwraps from disk blob
        self.assertEqual(p2.get(1), plain1); self.assertEqual(p2.current_version(), 2)
        blob = self.all_disk_text(d)
        self.assertNotIn(plain1, blob); self.assertNotIn(plain1.hex().encode(), blob)
        self.assertNotIn(p2.get(2), blob)

    def test_aws_kms_through_core(self):
        os.environ["ATL_KEY_PROVIDER"] = "aws-kms"
        import atl.keys as K
        kms = FakeKMS()
        orig = K.AwsKmsProvider.__init__
        K.AwsKmsProvider.__init__ = lambda self, d, client=None, key_id=None: orig(self, d, client=kms, key_id="k")
        try:
            d = mk(); c = Core(d)
            w = c.admin_principal("issue", T, "w")
            c.rotate_master()
            self.assertEqual(c.invoke(sign_request(w["secret"], T, "w", 1, "echo", {"text": "x"}))["status"], 200)
            self.assertTrue(Core(d).verify_all(T)["ok"])
            self.assertFalse((d / "master.key").exists())
        finally:
            K.AwsKmsProvider.__init__ = orig

    def _vault(self):
        FakeVault.store = {}
        srv = HTTPServer(("127.0.0.1", 0), FakeVault)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}"

    def test_vault_kv_rotation_and_no_disk(self):
        addr = self._vault(); d = mk()
        p = VaultKVProvider(d, addr=addr, token="tok")
        k1 = p.get(1)
        self.assertEqual(p.rotate(), 2)
        p2 = VaultKVProvider(d, addr=addr, token="tok")
        self.assertEqual((p2.current_version(), p2.get(1)), (2, k1))
        self.assertNotIn(k1.hex().encode(), self.all_disk_text(d))
        with self.assertRaises(KeyError_):
            VaultKVProvider(d, addr=addr, token="bad")

    def test_vault_transit(self):
        addr = self._vault(); d = mk()
        p = VaultTransitProvider(d, addr=addr, token="tok", key="atl")
        k1 = p.get(1); p.rotate()
        p2 = VaultTransitProvider(d, addr=addr, token="tok", key="atl")
        self.assertEqual((p2.get(1), p2.current_version()), (k1, 2))
        self.assertNotIn(k1.hex().encode(), self.all_disk_text(d))

    def test_vault_through_core(self):
        addr = self._vault()
        os.environ.update(ATL_KEY_PROVIDER="vault", ATL_VAULT_ADDR=addr, ATL_VAULT_TOKEN="tok")
        d = mk(); c = Core(d)
        w = c.admin_principal("issue", T, "w"); c.rotate_master()
        self.assertEqual(c.invoke(sign_request(w["secret"], T, "w", 1, "echo", {"text": "x"}))["status"], 200)
        self.assertTrue(Core(d).verify_all(T)["ok"])
        self.assertFalse((d / "master.key").exists())


if __name__ == "__main__":
    unittest.main()
