import json
import tempfile
import unittest
from pathlib import Path

from mcr.analyze import parse_finding
from mcr.models import Source
from mcr.pipeline import run
from mcr.scrape import SnapshotStore
from mcr.submit import FileSink

SRC = Source("city-a", "City A", "https://example.gov/code")
V1 = "<html><body><p>12.4.030 Noise limits</p><p>Max 70 dB.</p><p>12.5.010 Signs</p><p>Max 20 sq ft.</p></body></html>"
V2 = V1.replace("70 dB", "65 dB after 2027-01-01")
GOOD = json.dumps({"summary": "Noise limit lowered", "severity": "major", "confidence": 0.9,
                   "affected_rules": ["noise-limit"], "required_actions": ["Update limit to 65 dB"],
                   "effective_date": "2027-01-01"})


class T(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.store = SnapshotStore(self.d / "s")
        self.sink = FileSink(self.d / "a.jsonl")

    def alerts(self):
        p = self.d / "a.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def test_baseline_then_change_then_idempotent(self):
        r = run([SRC], self.store, lambda s, u: GOOD, self.sink, fetch=lambda u: V1)
        self.assertEqual(r.baselined, ["city-a"])
        r = run([SRC], self.store, lambda s, u: GOOD, self.sink, fetch=lambda u: V2)
        self.assertEqual(r.submitted, 1)
        a = self.alerts()
        self.assertEqual(a[0]["section"], "12.4.030")
        self.assertEqual(a[0]["patches"][0]["rule_id"], "noise-limit")
        r = run([SRC], self.store, lambda s, u: GOOD, self.sink, fetch=lambda u: V2)
        self.assertEqual(r.submitted, 0)
        self.assertEqual(len(self.alerts()), 1)

    def test_low_confidence_keeps_baseline(self):
        run([SRC], self.store, lambda s, u: GOOD, self.sink, fetch=lambda u: V1)
        low = GOOD.replace("0.9", "0.2")
        r = run([SRC], self.store, lambda s, u: low, self.sink, fetch=lambda u: V2)
        self.assertEqual(r.low_confidence, ["city-a:12.4.030"])
        self.assertEqual(self.alerts(), [])
        r = run([SRC], self.store, lambda s, u: GOOD, self.sink, fetch=lambda u: V2)
        self.assertEqual(r.submitted, 1)

    def test_bad_llm_output_isolated(self):
        run([SRC], self.store, lambda s, u: GOOD, self.sink, fetch=lambda u: V1)
        r = run([SRC], self.store, lambda s, u: "nope", self.sink, fetch=lambda u: V2)
        self.assertEqual(len(r.errors), 1)
        self.assertEqual(self.alerts(), [])

    def test_fetch_error_isolated(self):
        def boom(u):
            raise OSError("down")
        r = run([SRC], self.store, lambda s, u: GOOD, self.sink, fetch=boom)
        self.assertEqual(len(r.errors), 1)

    def test_parse_rejects_bad_severity(self):
        with self.assertRaises(ValueError):
            parse_finding("x", GOOD.replace("major", "huge"))


if __name__ == "__main__":
    unittest.main()
