"""AT-01..AT-03: AQPD contract + reference engine. (Real AQPD: BLOCKED, not in repository.)"""
import unittest

from ctal.aqpd import AqpdResult, ReferenceAqpdEngine

POL = {"policy_id": "p", "version": 3, "max_bytes": 100, "reject_patterns": ["bad thing"], "warn_patterns": ["meh"]}


class AqpdTests(unittest.TestCase):
    e = ReferenceAqpdEngine()

    def test_at01_benign(self):
        r = self.e.assess(b"all good here", "text/plain", POL)
        self.assertEqual((r.status, r.policy_id, r.policy_version), ("ACCEPT", "p", 3))
        self.assertTrue(r.evidence_refs and r.reason_codes and r.engine_version)

    def test_at02_adversarial_and_warn(self):
        self.assertEqual(self.e.assess(b"this is a BAD THING!", "text/plain", POL).status, "REJECT")
        self.assertEqual(self.e.assess(b"meh", "text/plain", POL).status, "WARN")

    def test_at03_bounds_and_malformed(self):
        self.assertEqual(self.e.assess(b"x" * 101, "text/plain", POL).reason_codes, ["SUBJECT_TOO_LARGE"])
        self.assertEqual(self.e.assess(b"x" * 10_000_000, "text/plain", {**POL, "max_bytes": 10 ** 9}).status, "REJECT")
        for data, code in [(b'{"a":1,"a":2}', "DUPLICATE_KEY"), (b'[' * 40 + b']' * 40, "TOO_DEEP"), (b'{', "MALFORMED_JSON")]:
            r = self.e.assess(data, "application/json", POL)
            self.assertEqual((r.status, r.reason_codes), ("REJECT", ["MALFORMED_SUBJECT:" + code]))
        self.assertEqual(self.e.assess(b"\xff\xfe", "text/plain", POL).reason_codes, ["INVALID_UTF8"])
        self.assertEqual(self.e.assess("not bytes", "text/plain", POL).status, "ERROR")

    def test_invalid_status_cannot_be_constructed(self):
        with self.assertRaises(ValueError):
            AqpdResult("a", "MAYBE", "p", 1, "e")


if __name__ == "__main__":
    unittest.main()
