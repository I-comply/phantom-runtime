"""AT-07 envelope signature; AT-08 decision matrix (exhaustive)."""
import copy
import itertools
import unittest

from ctal.aqpd import AqpdResult
from ctal.cles import ClesResult
from ctal.contracts import AQPD_STATUSES, CLES_STATUSES, decide
from ctal.envelope import build_and_sign, validate_schema, verify_envelope
from ctal.tests.helpers import World


def make(w, aq="ACCEPT", cl="AUTHORIZED", dp=None):
    return build_and_sign(
        tenant_id="acme", subject_digest="b" * 64, media_type="text/plain", subject_evidence_refs=["sha256:" + "b" * 64],
        aqpd=AqpdResult("asm-1", aq, "pol", 1, "eng-1", ["R"], ["e1"]),
        cles=ClesResult(cl, ["R"], True, "lic", "prod", "iss", "iss-1", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                        "2026-06-01T12:00:00Z"),
        policy_bundle_digest="c" * 64, software_release_digest="d" * 64,
        decision_policy=dp or {"decision_policy_id": "x", "version": 1, "warn_action": "HOLD_FOR_REVIEW"},
        signer=w.env_s, clock=w.clock)


def paths(o, prefix=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from paths(v, prefix + (k,))
    elif isinstance(o, list) and o:
        for i, v in enumerate(o):
            yield from paths(v, prefix + (i,))
    else:
        yield prefix


def set_path(o, p, val):
    for k in p[:-1]:
        o = o[k]
    o[p[-1]] = val


def get_path(o, p):
    for k in p:
        o = o[k]
    return o


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def test_valid_envelope_verifies_and_schema_clean(self):
        env = make(self.w)
        self.assertEqual(validate_schema(env), [])
        r = verify_envelope(env, self.w.public, expected_tenant="acme", now=self.w.clock())
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(env["decision"]["outcome"], "PROCEED")

    def test_at07_every_field_change_fails(self):
        env = make(self.w)
        n = 0
        for p in paths(env):
            if p == ("signing", "signature"):
                continue
            mutated = copy.deepcopy(env)
            old = get_path(mutated, p)
            set_path(mutated, p, (not old) if isinstance(old, bool) else (old + 1 if isinstance(old, int) else str(old) + "x"))
            r = verify_envelope(mutated, self.w.public, expected_tenant="acme", now=self.w.clock())
            self.assertFalse(r.ok, "mutation of %s was accepted" % (p,))
            n += 1
        self.assertGreater(n, 25)

    def test_added_removed_and_replaced_parts_fail(self):
        env = make(self.w)
        extra = copy.deepcopy(env)
        extra["x"] = 1
        self.assertFalse(verify_envelope(extra, self.w.public).ok)
        for k in list(env):
            m = copy.deepcopy(env)
            del m[k]
            self.assertFalse(verify_envelope(m, self.w.public).ok, k)
        sig = copy.deepcopy(env)
        sig["signing"]["signature"] = make(self.w, "REJECT")["signing"]["signature"]
        self.assertFalse(verify_envelope(sig, self.w.public).ok)

    def test_untrusted_algorithm_key_canon_and_tenant(self):
        env = make(self.w)
        for path, val, err in [(("signing", "algorithm"), "HS256", "ALGORITHM_NOT_ALLOWED"),
                               (("signing", "canonicalization_id"), "other", "CANONICALIZATION_NOT_ALLOWED"),
                               (("signing", "key_id"), "unknown", "UNKNOWN_KEY_ID")]:
            m = copy.deepcopy(env)
            set_path(m, path, val)
            self.assertEqual(verify_envelope(m, self.w.public).errors, [err])
        self.assertEqual(verify_envelope(env, self.w.public, expected_tenant="globex").errors, ["TENANT_MISMATCH"])
        self.w.public.set_status("env-1", "revoked")
        self.assertEqual(verify_envelope(env, self.w.public).errors, ["KEY_REVOKED"])

    def test_validly_signed_but_inconsistent_decision_is_rejected(self):
        env = make(self.w, "REJECT", "AUTHORIZED")
        env["decision"]["outcome"] = "PROCEED"
        from ctal.envelope import signing_input
        env["signing"]["signature"] = self.w.env_s.sign(signing_input(env))  # attacker/bug with a valid key
        self.assertEqual(verify_envelope(env, self.w.public).errors, ["DECISION_INCONSISTENT_WITH_AQPD_CLES"])

    def test_replay_freshness_option(self):
        env = make(self.w)
        self.w.clock.advance(hours=2)
        self.assertTrue(verify_envelope(env, self.w.public, now=self.w.clock()).ok)
        self.assertEqual(verify_envelope(env, self.w.public, now=self.w.clock(), max_age_seconds=300).errors,
                         ["ENVELOPE_STALE_OR_FUTURE"])

    def test_at08_matrix_exhaustive(self):
        proceeds = []
        for a, c in itertools.product(AQPD_STATUSES, CLES_STATUSES):
            o, reasons = decide(a, c)
            self.assertIn(o, ("PROCEED", "BLOCK", "HOLD_FOR_REVIEW", "ERROR"))
            self.assertTrue(reasons)
            if o == "PROCEED":
                proceeds.append((a, c))
        self.assertEqual(proceeds, [("ACCEPT", "AUTHORIZED")])
        self.assertEqual(decide("ACCEPT", "DENIED")[0], "BLOCK")
        self.assertEqual(decide("REJECT", "AUTHORIZED")[0], "BLOCK")
        self.assertEqual(decide("WARN", "AUTHORIZED")[0], "HOLD_FOR_REVIEW")
        self.assertEqual(decide("ACCEPT", "ERROR")[0], "ERROR")
        for bad in (None, "", "accept", "ACCEPT ", 7, object()):
            self.assertEqual(decide(bad, "AUTHORIZED")[0], "ERROR")
            self.assertEqual(decide("ACCEPT", bad)[0], "ERROR")
        self.assertEqual(decide("ACCEPT", "AUTHORIZED", checks_ok=False)[0], "BLOCK")

    def test_warn_proceed_only_by_explicit_versioned_policy(self):
        dp = {"decision_policy_id": "lenient", "version": 2, "warn_action": "PROCEED"}
        self.assertEqual(decide("WARN", "AUTHORIZED", True, dp)[0], "PROCEED")
        self.assertEqual(decide("WARN", "DENIED", True, dp)[0], "BLOCK")
        self.assertEqual(decide("QUARANTINE", "AUTHORIZED", True, dp)[0], "BLOCK")
        env = make(self.w, "WARN", "AUTHORIZED", dp)
        self.assertEqual(env["decision"]["outcome"], "PROCEED")
        self.assertTrue(verify_envelope(env, self.w.public, decision_policy=dp).ok)
        self.assertFalse(verify_envelope(env, self.w.public).ok)  # default policy would not allow it

    def test_json_schema_agrees_when_available(self):
        try:
            import json, os
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        path = os.path.join(os.path.dirname(__file__), "..", "schemas", "assurance-envelope.v1.schema.json")
        with open(path) as f:
            schema = json.load(f)
        env = make(self.w)
        jsonschema.validate(env, schema)
        bad = copy.deepcopy(env)
        bad["aqpd"]["status"] = "MAYBE"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
        self.assertNotEqual(validate_schema(bad), [])


if __name__ == "__main__":
    unittest.main()
