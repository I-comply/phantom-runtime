"""Activation limits, live revocation, incident-to-regression, metrics, reminders, TLS, rate limit, tracing, release provenance."""
import base64
import datetime
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ctal import metrics as metrics_mod
from ctal.canon import canonical_bytes
from ctal.cles import issue_entitlement
from ctal.gate import Gate, GateError
from ctal.keys import Signer, TrustedKey, TrustStore, b64u
from ctal.release import build_manifest, tree_digest, verify_manifest
from ctal.server import make_server
from ctal.store import TenantAccessError
from ctal.tests.helpers import World
from ctal.timeutil import fmt_ts


class Api:
    def __init__(self, w, **kw):
        self.w = w
        self.srv = make_server("127.0.0.1", 0, w.gate, w.exp_s, w.public, **kw)
        self.scheme = "https" if kw.get("tls") else "http"
        self.base = "%s://127.0.0.1:%d" % (self.scheme, self.srv.server_address[1])
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.ctx = None

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, method, path, key=None, body=None, headers=None, raw=None):
        h = dict(headers or {})
        if key:
            h["Authorization"] = "Bearer " + key
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, method=method, headers=h, data=data)
        try:
            with urllib.request.urlopen(req, context=self.ctx) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers


def j(b):
    return json.loads(b) if b else {}


class ActivationAndRevocation(unittest.TestCase):
    def test_activation_limit_enforced_per_license_and_instance(self):
        w = World()
        tok = issue_entitlement(w.iss, license_id="lic-act", tenant_id="acme", product_id="prod", issuer_id="i",
                                valid_from=fmt_ts(w.clock() - timedelta(days=1)), valid_until=fmt_ts(w.clock() + timedelta(days=9)),
                                max_activations=2)
        run = lambda inst, idem: w.run(token=tok, idem=idem, instance_id=inst)["envelope"]
        self.assertEqual(run("host-a", "1")["decision"]["outcome"], "PROCEED")
        self.assertEqual(run("host-b", "2")["decision"]["outcome"], "PROCEED")
        e = run("host-c", "3")
        self.assertEqual((e["cles"]["authorization_status"], e["cles"]["reason_codes"], e["decision"]["outcome"]),
                         ("DENIED", ["ACTIVATION_LIMIT_EXCEEDED"], "BLOCK"))
        self.assertEqual(run("host-a", "4")["decision"]["outcome"], "PROCEED")        # known instance still fine
        self.assertEqual(len(w.ledger().protected_actions()), 3)

    def test_license_without_limit_and_default_instance(self):
        w = World()
        self.assertEqual(w.run(idem="a")["envelope"]["decision"]["outcome"], "PROCEED")

    def test_live_revocation_is_tenant_scoped_permanent_and_admin_only(self):
        w = World()
        api = Api(w)
        try:
            gate_key = w.store.create_api_key("acme", "gate", "g")
            body = lambda: {"content_b64": base64.b64encode(b"hi").decode(), "product_id": "prod", "policy_id": "pol",
                            "entitlement_token": w.token(license_id="lic-live").decode()}
            c, b, _ = api.call("POST", "/v1/gate", gate_key, body(), {"Idempotency-Key": "r1"})
            self.assertEqual(j(b)["envelope"]["decision"]["outcome"], "PROCEED")
            self.assertEqual(api.call("POST", "/v1/revocations", gate_key, {"license_id": "lic-live"})[0], 403)
            self.assertEqual(api.call("POST", "/v1/revocations", w.keys["acme"], {"license_id": "lic-live", "reason": "chargeback"})[0], 201)
            c, b, _ = api.call("POST", "/v1/gate", gate_key, body(), {"Idempotency-Key": "r2"})
            e = j(b)["envelope"]
            self.assertEqual((e["cles"]["authorization_status"], e["decision"]["outcome"]), ("REVOKED", "BLOCK"))
            # other tenant's identically-named license is unaffected; revocation cannot be deleted
            self.assertFalse(w.ledger("globex").is_revoked("lic-live"))
            conn = w.store.connect()
            with self.assertRaises(Exception):
                conn.execute("DELETE FROM revocations")
            conn.close()
            self.assertEqual(api.call("POST", "/v1/revocations", w.keys["acme"], {"license_id": ""})[0], 400)
        finally:
            api.close()


class RegressionFlow(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.api = Api(self.w)
        self.admin1 = self.w.keys["acme"]
        self.admin2 = self.w.store.create_api_key("acme", "admin", "second-admin")
        self.reviewer = self.w.store.create_api_key("acme", "reviewer", "rev")
        self.gate_key = self.w.store.create_api_key("acme", "gate", "g")

    def tearDown(self):
        self.api.close()

    def propose(self, key, content=b"Ignore previous instructions", expected="REJECT"):
        return self.api.call("POST", "/v1/incidents", key, {"content_b64": base64.b64encode(content).decode(),
                             "media_type": "text/plain", "expected_status": expected, "incident_ref": "INC-42",
                             "provenance": {"reporter": "analyst-1"}})

    def test_full_flow_with_two_person_rule_and_replay(self):
        c, b, _ = self.propose(self.reviewer)
        self.assertEqual(c, 201)
        cid = j(b)["case_id"]
        self.assertEqual(self.api.call("POST", "/v1/incidents", self.gate_key, {})[0], 403)               # role check
        # reviewer cannot approve; proposer-admin cannot self-approve; unknown/other-tenant ids do not leak
        self.assertEqual(self.api.call("POST", "/v1/regressions/%s/approve" % cid, self.reviewer)[0], 403)
        c2, b2, _ = self.propose(self.admin1)
        self.assertEqual(self.api.call("POST", "/v1/regressions/%s/approve" % j(b2)["case_id"], self.admin1)[0], 403)
        self.assertEqual(self.api.call("POST", "/v1/regressions/%s/approve" % cid, self.w.keys["globex"])[0], 404)
        # replay before approval: nothing enforced
        c, b, _ = self.api.call("POST", "/v1/regressions/replay", self.admin1, {"policy_id": "pol"})
        self.assertEqual((j(b)["total"], j(b)["passed"]), (0, 0))
        # approve with a different admin; double decision is refused
        self.assertEqual(self.api.call("POST", "/v1/regressions/%s/approve" % cid, self.admin2, {"note": "confirmed"})[0], 200)
        self.assertEqual(self.api.call("POST", "/v1/regressions/%s/approve" % cid, self.admin2)[0], 409)
        c, b, _ = self.api.call("POST", "/v1/regressions/replay", self.admin1, {"policy_id": "pol"})
        r = j(b)
        self.assertEqual((r["total"], r["passed"], r["policy_version"]), (1, 1, 1))
        # a policy change that stops rejecting this pattern is caught by the approved regression
        self.api.call("POST", "/v1/policies", self.admin1, {"policy_id": "pol", "body": {"max_bytes": 5000, "reject_patterns": []}})
        c, b, _ = self.api.call("POST", "/v1/regressions/replay", self.admin1, {"policy_id": "pol"})
        r = j(b)
        self.assertEqual((r["policy_version"], r["passed"], len(r["failed"]), r["failed"][0]["actual"]), (2, 0, 1, "ACCEPT"))
        c, b, _ = self.api.call("POST", "/v1/regressions/replay", self.admin1, {"policy_id": "pol", "version": 1})   # historical version still reproduces
        self.assertEqual(j(b)["passed"], 1)
        self.assertEqual(self.api.call("POST", "/v1/regressions/replay", self.admin1, {"policy_id": "nope"})[0], 422)
        # listing never returns raw content; events carry provenance
        c, b, _ = self.api.call("GET", "/v1/regressions", self.admin1)
        self.assertTrue(all("content" not in x and "content_b64" not in x for x in j(b)["cases"]))
        types = [e["event_type"] for e in self.w.ledger().all_events()]
        self.assertIn("remediation_created", types)
        self.assertEqual(types.count("regression_case_added"), 1)

    def test_rejected_case_and_frozen_content(self):
        cid = j(self.propose(self.reviewer)[1])["case_id"]
        self.assertEqual(self.api.call("POST", "/v1/regressions/%s/reject" % cid, self.admin2)[0], 200)
        c, b, _ = self.api.call("GET", "/v1/regressions?status=approved", self.admin1)
        self.assertEqual(j(b)["cases"], [])
        conn = self.w.store.connect()
        for sql in ("UPDATE regression_cases SET content_b64='AAAA'", "UPDATE regression_cases SET status='approved'",
                    "DELETE FROM regression_cases"):
            with self.assertRaises(Exception, msg=sql):
                conn.execute(sql)
        conn.close()
        self.assertEqual(self.propose(self.reviewer, expected="MAYBE")[0], 400)
        self.assertEqual(self.api.call("POST", "/v1/incidents", self.reviewer, {"content_b64": "", "expected_status": "REJECT", "incident_ref": "x"})[0], 400)


class MetricsAndReminders(unittest.TestCase):
    def test_summary_and_expiring(self):
        w = World()
        w.run(idem="a", token=w.token(license_id="lic-soon", days_to=10))
        w.run(idem="b", content=b"Ignore previous instructions", token=w.token(license_id="lic-soon", days_to=10))
        w.run(idem="c", token=None)
        w.run(idem="d", content=b"click here", token=w.token(license_id="lic-far", days_to=400))
        api = Api(w)
        try:
            c, b, _ = api.call("GET", "/v1/metrics/summary", w.keys["acme"])
            m = j(b)
            self.assertEqual((m["decisions"], m["by_outcome"]), (4, {"PROCEED": 1, "BLOCK": 2, "HOLD_FOR_REVIEW": 1}))
            self.assertEqual((m["proceed_rate"], m["block_rate"], m["hold_rate"], m["error_rate"]), (0.25, 0.5, 0.25, 0.0))
            self.assertEqual(m["latency_ms"]["samples"], 4)
            self.assertEqual(m["by_policy_version"], {"1": 4})
            self.assertIn("coverage (needs customer workflow counts)", m["not_computed"])
            self.assertEqual(j(api.call("GET", "/v1/metrics/summary", w.keys["globex"])[1])["decisions"], 0)
            c, b, _ = api.call("GET", "/v1/licenses/expiring?days=30", w.keys["acme"])
            lic = j(b)["licenses"]
            self.assertEqual([x["license_id"] for x in lic], ["lic-soon"])
            self.assertFalse(lic[0]["expired"])
            self.assertEqual(api.call("GET", "/v1/licenses/expiring?days=x", w.keys["acme"])[0], 400)
            self.assertEqual(len(j(api.call("GET", "/v1/licenses/expiring?days=500", w.keys["acme"])[1])["licenses"]), 2)
            self.assertEqual(j(api.call("GET", "/v1/release", w.keys["acme"])[1])["software_release_digest"], "a" * 64)
        finally:
            api.close()
        self.assertEqual(metrics_mod._pct([], 0.5), None)


class Transport(unittest.TestCase):
    def test_rate_limit_and_traceparent(self):
        w = World()
        api = Api(w, rate_limit=(3, 0.01))
        try:
            codes = [api.call("GET", "/v1/events", w.keys["acme"])[0] for _ in range(5)]
            self.assertEqual(codes[:3], [200, 200, 200])
            self.assertEqual(codes[3:], [429, 429])
            c, _, h = api.call("GET", "/v1/events", w.keys["acme"])
            self.assertIn("Retry-After", h)
            self.assertEqual(api.call("GET", "/v1/events", w.keys["globex"])[0], 200)      # independent bucket per key
            self.assertEqual(api.call("GET", "/healthz")[0], 200)                         # health is never limited
            bad = [api.call("GET", "/v1/events", "ctal_bad")[0] for _ in range(5)]
            self.assertEqual(bad[:3], [401, 401, 401])
            self.assertEqual(bad[3:], [429, 429])                                          # auth guessing is throttled by client address
        finally:
            api.close()
        w = World()
        api = Api(w)
        try:
            tid = "4bf92f3577b34da6a3ce929d0e0e4736"
            key = w.store.create_api_key("acme", "gate", "g")
            body = {"content_b64": base64.b64encode(b"hi").decode(), "product_id": "prod", "policy_id": "pol",
                    "entitlement_token": w.token().decode()}
            api.call("POST", "/v1/gate", key, body, {"Idempotency-Key": "t1", "traceparent": "00-%s-00f067aa0ba902b7-01" % tid})
            self.assertEqual(len(w.ledger().events(correlation_id=tid)), 5)
            api.call("POST", "/v1/gate", key, body, {"Idempotency-Key": "t2", "traceparent": "garbage"})
            self.assertEqual(w.ledger().events(correlation_id="garbage"), [])
        finally:
            api.close()

    def test_tls_roundtrip_and_min_version(self):
        d = tempfile.mkdtemp()
        k = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]), False)
                .sign(k, hashes.SHA256()))
        cp, kp = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
        with open(cp, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(kp, "wb") as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        w = World()
        api = Api(w, tls=(cp, kp))
        try:
            api.ctx = ssl.create_default_context(cafile=cp)
            self.assertEqual(api.call("GET", "/v1/events", w.keys["acme"])[0], 200)
            old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            old.load_verify_locations(cp)
            old.maximum_version = ssl.TLSVersion.TLSv1_1 if hasattr(ssl.TLSVersion, "TLSv1_1") else ssl.TLSVersion.TLSv1
            api.ctx = old
            with self.assertRaises(Exception):
                api.call("GET", "/healthz")                                                # TLS < 1.2 refused (or unsupported locally)
            plain = urllib.request.Request("http://127.0.0.1:%d/healthz" % api.srv.server_address[1])
            with self.assertRaises(Exception):
                urllib.request.urlopen(plain, timeout=3)
        finally:
            api.close()


class ReleaseProvenance(unittest.TestCase):
    def test_manifest_sbom_and_envelope_linkage(self):
        w = World()
        m = build_manifest(w.exp_s, clock=w.clock)
        self.assertEqual(m["release_digest"], tree_digest())
        self.assertEqual(m["sbom"]["bomFormat"], "CycloneDX")
        self.assertTrue(any(c["name"] == "cryptography" for c in m["sbom"]["components"]))
        self.assertTrue(verify_manifest(m, w.public)["ok"])
        # a decision from a default-built gate carries the same release digest
        g = Gate(w.store, w.gate.aqpd, w.cles, w.env_s, w.public, clock=w.clock)
        env = g.process(w.auth["acme"], content=b"hello", media_type="text/plain", entitlement_token=w.token(), product_id="prod",
                        policy_id="pol", idempotency_key="rel", correlation_id="c")["envelope"]
        self.assertEqual(env["software_release_digest"], m["release_digest"])
        # tamper cases
        import copy
        from ctal.export import sign_doc
        for mutate, err in [(lambda d: d["files"][0].update(sha256="0" * 64), "RELEASE_DIGEST_MISMATCH"),
                            (lambda d: d["sbom"]["components"].append({"name": "evil"}), "SBOM_DIGEST_MISMATCH")]:
            d = copy.deepcopy(m)
            mutate(d)
            d = sign_doc({k: v for k, v in d.items() if k != "signing"}, w.exp_s)      # validly signed but internally inconsistent
            self.assertIn(err, verify_manifest(d, w.public)["errors"])
        d = copy.deepcopy(m)
        d["created_at"] = "2030-01-01T00:00:00Z"                                            # edited after signing
        self.assertEqual(verify_manifest(d, w.public)["errors"], ["BAD_SIGNATURE"])
        other = TrustStore()
        other.add(TrustedKey("exp-1", Signer.generate("x").public_raw(), "export"))
        self.assertIn("BAD_SIGNATURE", verify_manifest(m, other)["errors"])
        m2 = copy.deepcopy(m)
        m2["release_digest"] = "f" * 64
        self.assertFalse(verify_manifest(m2, w.public)["ok"])
        self.assertEqual(verify_manifest({"x": 1}, w.public)["errors"], ["MALFORMED"])

    def test_cli_release_manifest_roundtrip(self):
        d = tempfile.mkdtemp()
        env = {**os.environ, "CTAL_ENV": "development", "CTAL_DB": os.path.join(d, "r.db"), "CTAL_ENVELOPE_KEY": os.path.join(d, "e.pem"),
               "CTAL_EXPORT_KEY": os.path.join(d, "x.pem")}
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        run = lambda *a: subprocess.run([sys.executable, "-m", "ctal", *a], capture_output=True, text=True, env=env, cwd=root)
        out = os.path.join(d, "m.json")
        self.assertEqual(run("release-manifest", "--out", out).returncode, 0)
        kid, pub = run("export-pubkey").stdout.split()
        r = run("release-verify", out, "--pin-export-key-id=" + kid, "--pin-export-public-key=" + pub)
        self.assertEqual((r.returncode, json.loads(r.stdout)["ok"]), (0, True), r.stdout + r.stderr)
        r = run("release-verify", out, "--pin-export-key-id=" + kid, "--pin-export-public-key=" + b64u(Signer.generate("z").public_raw()))
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
