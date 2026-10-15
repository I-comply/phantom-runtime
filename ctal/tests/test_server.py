"""API: authentication, RBAC, cross-tenant read/write/search/export (AT-09), limits, key lifecycle."""
import base64
import json
import threading
import unittest
import urllib.error
import urllib.request

from ctal.envelope import verify_envelope
from ctal.server import make_server
from ctal.tests.helpers import World


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World()
        cls.srv = make_server("127.0.0.1", 0, cls.w.gate, cls.w.exp_s, cls.w.public)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.keys = cls.w.keys
        cls.gate_key = cls.w.store.create_api_key("acme", "gate", "acme-gate")
        cls.aud_key = cls.w.store.create_api_key("acme", "auditor", "acme-aud")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, method, path, key=None, body=None, idem=None, raw=None, headers=None):
        h = dict(headers or {})
        if key:
            h["Authorization"] = "Bearer " + key
        if idem:
            h["Idempotency-Key"] = idem
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, method=method, headers=h, data=data)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def gate_body(self, tenant="acme", content=b"fine", **kw):
        b = {"content_b64": base64.b64encode(content).decode(), "media_type": "text/plain", "product_id": "prod",
             "policy_id": "pol", "entitlement_token": self.w.token(tenant=tenant).decode()}
        b.update(kw)
        return b

    def test_health_and_auth(self):
        self.assertEqual(self.call("GET", "/healthz")[0], 200)
        self.assertEqual(self.call("GET", "/readyz")[0], 200)
        for key in (None, "ctal_wrong", "x" * 300):
            self.assertEqual(self.call("POST", "/v1/gate", key, self.gate_body(), idem="a")[0], 401)
        self.assertEqual(self.call("GET", "/v1/events")[0], 401)

    def test_gate_roundtrip_and_replay(self):
        c, b = self.call("POST", "/v1/gate", self.gate_key, self.gate_body(), idem="api-1")
        self.assertEqual(c, 201)
        env = json.loads(b)["envelope"]
        self.assertEqual(env["decision"]["outcome"], "PROCEED")
        self.assertTrue(verify_envelope(env, self.w.public, expected_tenant="acme", now=self.w.clock()).ok)
        c, b = self.call("POST", "/v1/gate", self.gate_key, self.gate_body(), idem="api-1")
        self.assertEqual((c, json.loads(b)["replayed"]), (200, True))
        self.assertEqual(self.call("POST", "/v1/gate", self.gate_key, self.gate_body())[0], 400)  # missing Idempotency-Key
        self.assertEqual(self.call("POST", "/v1/gate", self.gate_key, self.gate_body(content=b"other"), idem="api-1")[0], 409)

    def test_metrics_admin_only(self):
        self.assertEqual(self.call("GET", "/v1/metrics", self.aud_key)[0], 403)
        c, b = self.call("GET", "/v1/metrics", self.keys["acme"])
        self.assertEqual(c, 200)
        self.assertIn("decisions", json.loads(b))

    def test_rbac(self):
        self.assertEqual(self.call("POST", "/v1/gate", self.aud_key, self.gate_body(), idem="r1")[0], 403)
        self.assertEqual(self.call("GET", "/v1/events", self.gate_key)[0], 403)
        self.assertEqual(self.call("GET", "/v1/export", self.gate_key)[0], 403)
        self.assertEqual(self.call("POST", "/v1/policies", self.gate_key, {"policy_id": "p", "body": {}})[0], 403)
        self.assertEqual(self.call("POST", "/v1/policies", self.aud_key, {"policy_id": "p", "body": {}})[0], 403)
        self.assertEqual(self.call("GET", "/v1/events", self.aud_key)[0], 200)
        self.assertEqual(self.call("GET", "/v1/export", self.aud_key)[0], 200)

    def test_at09_cross_tenant_read_write_search_export(self):
        c, b = self.call("POST", "/v1/gate", self.keys["acme"], self.gate_body(), idem="x-acme")
        acme_env = json.loads(b)["envelope"]
        # read: globex cannot fetch acme's envelope by id
        self.assertEqual(self.call("GET", "/v1/envelopes/" + acme_env["envelope_id"], self.keys["globex"])[0], 404)
        self.assertEqual(self.call("GET", "/v1/envelopes/" + acme_env["envelope_id"], self.keys["acme"])[0], 200)
        # write: claiming another tenant in the body is refused and not executed
        before = len(self.w.ledger("globex").protected_actions())
        c, b = self.call("POST", "/v1/gate", self.keys["acme"], self.gate_body(tenant_id="globex"), idem="x-claim")
        self.assertEqual((c, json.loads(b)["error"]), (403, "TENANT_MISMATCH"))
        self.assertEqual(len(self.w.ledger("globex").protected_actions()), before)
        # token minted for another tenant cannot authorize (CLES tenant scope)
        c, b = self.call("POST", "/v1/gate", self.keys["acme"], self.gate_body(tenant="globex"), idem="x-tok")
        env = json.loads(b)["envelope"]
        self.assertEqual((env["cles"]["authorization_status"], env["decision"]["outcome"]), ("DENIED", "BLOCK"))
        # search: results are tenant-bound even when filtering by another tenant's digest/correlation
        c, b = self.call("GET", "/v1/events?subject_digest=" + acme_env["subject"]["digest"], self.keys["globex"])
        self.assertEqual(json.loads(b)["events"], [])
        c, b = self.call("GET", "/v1/events?limit=500", self.keys["globex"])
        self.assertTrue(all(e["tenant_id"] == "globex" for e in json.loads(b)["events"]))
        # export: only own tenant
        c, z = self.call("GET", "/v1/export", self.keys["globex"])
        import io, zipfile
        zf = zipfile.ZipFile(io.BytesIO(z))
        self.assertEqual(json.loads(zf.read("manifest.json"))["tenant_id"], "globex")
        self.assertNotIn(acme_env["envelope_id"].encode(), zf.read("envelopes.jsonl"))
        self.assertNotIn(b'"tenant_id":"acme"', zf.read("events.jsonl"))
        # policy publish writes only to own tenant
        self.call("POST", "/v1/policies", self.keys["globex"], {"policy_id": "gpol", "body": {"max_bytes": 5}})
        self.assertIsNone(self.w.ledger("acme").get_policy("gpol"))

    def test_input_limits_and_malformed(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        conn.putrequest("POST", "/v1/gate")
        for k, v in (("Authorization", "Bearer " + self.gate_key), ("Idempotency-Key", "big"), ("Content-Length", "2000000")):
            conn.putheader(k, v)
        conn.endheaders()  # declared oversize body is refused without reading it
        resp = conn.getresponse()
        self.assertEqual(resp.status, 413)
        resp.read()
        conn.close()
        self.assertEqual(self.call("POST", "/v1/gate", self.gate_key, raw=b'{"a":1,"a":2}', idem="dup")[0], 400)
        self.assertEqual(self.call("POST", "/v1/gate", self.gate_key, raw=b'[' * 3000, idem="deep")[0], 400)
        self.assertEqual(self.call("POST", "/v1/gate", self.gate_key, raw=b'{"content_b64":"!!!"}', idem="b64")[0], 400)
        c, b = self.call("POST", "/v1/gate", self.gate_key, {"content_b64": "", "product_id": "p", "policy_id": "nope"}, idem="np")
        self.assertEqual((c, json.loads(b)["error"]), (422, "POLICY_NOT_FOUND"))
        self.assertEqual(self.call("GET", "/v1/events?limit=abc", self.aud_key)[0], 400)
        self.assertEqual(self.call("GET", "/nope", self.aud_key)[0], 404)

    def test_errors_do_not_leak_internals(self):
        c, b = self.call("POST", "/v1/gate", self.gate_key, raw=b'{"content_b64":"AA==","product_id":1}', idem="t")
        self.assertIn(c, (400, 500))
        self.assertNotIn(b"Traceback", b)

    def test_key_rotation_and_revocation_lifecycle(self):
        from ctal.keys import Signer
        w = World()
        e_old = w.run(idem="pre")["envelope"]
        new = Signer.generate("env-2")
        leds = [w.ledger()]
        w.gate.rotate_envelope_key(new, leds, "admin")
        e_new = w.run(idem="post")["envelope"]
        self.assertEqual((e_old["signing"]["key_id"], e_new["signing"]["key_id"]), ("env-1", "env-2"))
        for e in (e_old, e_new):
            self.assertTrue(verify_envelope(e, w.public, now=w.clock()).ok)
        w.gate.revoke_key("env-1", leds, "admin", "SUSPECTED_COMPROMISE")
        self.assertEqual(verify_envelope(e_old, w.public, now=w.clock()).errors, ["KEY_REVOKED"])
        self.assertTrue(verify_envelope(e_new, w.public, now=w.clock()).ok)
        types = [e["event_type"] for e in leds[0].all_events() if e["event_type"].startswith("key_")]
        self.assertEqual(types, ["key_rotated", "key_revoked"])
        # unknown/never-trusted key is never silently trusted
        rogue = Signer.generate("env-9")
        from ctal.envelope import signing_input
        forged = json.loads(json.dumps(e_new)); forged["signing"]["key_id"] = "env-9"
        forged["signing"]["signature"] = rogue.sign(signing_input(forged))
        self.assertEqual(verify_envelope(forged, w.public, now=w.clock()).errors, ["UNKNOWN_KEY_ID"])


if __name__ == "__main__":
    unittest.main()
