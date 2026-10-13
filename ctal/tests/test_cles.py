"""AT-04..AT-06: CLES entitlement verification (reference verifier; real CLES BLOCKED)."""
import unittest

from ctal.canon import canonical_bytes, parse_strict
from ctal.cles import ClesVerifier
from ctal.keys import Signer, TrustedKey
from ctal.tests.helpers import World


class ClesTests(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def v(self, tok, tenant="acme", product="prod"):
        return self.w.cles.verify(tok, tenant, product)

    def test_at04_valid(self):
        r = self.v(self.w.token())
        self.assertEqual(r.authorization_status, "AUTHORIZED")
        self.assertTrue(r.entitlement_checked and r.revocation_checked_at and r.key_id == "iss-1")

    def test_at05_tamper_and_untrusted_keys(self):
        tok = parse_strict(self.w.token())
        tok["payload"]["valid_until"] = "2099-01-01T00:00:00Z"
        r = self.v(canonical_bytes(tok))
        self.assertEqual((r.authorization_status, r.reason_codes), ("INVALID_SIGNATURE", ["BAD_SIGNATURE"]))
        rogue = Signer.generate("iss-1")  # same id, different key
        self.assertEqual(self.v(self.w.token(signer=rogue)).authorization_status, "INVALID_SIGNATURE")
        unknown = Signer.generate("nobody")
        r = self.v(self.w.token(signer=unknown))
        self.assertEqual((r.authorization_status, r.reason_codes), ("INVALID_SIGNATURE", ["UNKNOWN_KEY_ID"]))

    def test_algorithm_chosen_by_token_is_rejected(self):
        tok = parse_strict(self.w.token())
        tok["signing"]["algorithm"] = "none"
        self.assertEqual(self.v(canonical_bytes(tok)).reason_codes, ["UNSUPPORTED_ALGORITHM"])

    def test_wrong_purpose_key_cannot_authorize(self):
        w = self.w
        w.issuer_trust.add(TrustedKey("env-as-issuer", w.env_s.public_raw(), "envelope"))
        self.assertEqual(self.v(w.token(signer=w.env_s)).authorization_status, "INVALID_SIGNATURE")

    def test_at06_lifecycle_negatives(self):
        w = self.w
        cases = [
            (w.token(days_from=-10, days_to=-1), "EXPIRED"), (w.token(days_from=1, days_to=10), "DENIED"),
            (w.token(tenant="globex"), "DENIED"), (w.token(product="other"), "DENIED"),
            (None, "DENIED"), (b"", "DENIED"), (b"not json", "DENIED"), (b"[]", "DENIED"), (b'{"payload":{},"signing":{}}', "DENIED"),
            (b'{"payload":{},"signing":{"algorithm":"Ed25519","key_id":"iss-1","signature":"AAAA"}}', "INVALID_SIGNATURE"),
        ]
        for tok, expect in cases:
            self.assertEqual(self.v(tok).authorization_status, expect, tok[:60] if tok else tok)
        w.revoked.revoked.add("lic-1")
        self.assertEqual(self.v(w.token()).authorization_status, "REVOKED")

    def test_reason_codes_for_scope(self):
        self.assertEqual(self.v(self.w.token(tenant="globex")).reason_codes, ["TENANT_MISMATCH"])
        self.assertEqual(self.v(self.w.token(product="x")).reason_codes, ["PRODUCT_MISMATCH"])

    def test_revoked_issuer_key_and_rotation(self):
        w = self.w
        new = Signer.generate("iss-2")
        w.issuer_trust.add(TrustedKey("iss-2", new.public_raw(), "entitlement"))
        old_tok, new_tok = w.token(), w.token(signer=new)
        self.assertEqual(self.v(old_tok).authorization_status, "AUTHORIZED")      # overlap period
        self.assertEqual(self.v(new_tok).authorization_status, "AUTHORIZED")
        w.issuer_trust.set_status("iss-1", "retired")                              # retired: still verifies
        self.assertEqual(self.v(old_tok).authorization_status, "AUTHORIZED")
        w.issuer_trust.set_status("iss-1", "revoked")
        self.assertEqual(self.v(old_tok).reason_codes, ["KEY_REVOKED"])
        self.assertEqual(self.v(new_tok).authorization_status, "AUTHORIZED")

    def test_internal_failures_are_error_not_success(self):
        class Boom:
            def is_revoked(self, _):
                raise RuntimeError("revocation feed down")
        c = ClesVerifier(self.w.issuer_trust, Boom(), clock=self.w.clock)
        r = c.verify(self.w.token(), "acme", "prod")
        self.assertEqual((r.authorization_status, r.reason_codes), ("ERROR", ["REVOCATION_CHECK_FAILED"]))
        self.assertEqual(c.verify(object(), "acme", "prod").authorization_status, "ERROR")


if __name__ == "__main__":
    unittest.main()
