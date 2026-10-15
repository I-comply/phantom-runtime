"""AT-14 secret hygiene + config/production key rules."""
import os
import stat
import subprocess
import sys
import tempfile
import unittest

from ctal.config import build_from_env, load_signer
from ctal.export import build_export
from ctal.tests.helpers import World

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCAN = os.path.join(ROOT, "tools", "scan_secrets.py")


class HygieneTests(unittest.TestCase):
    def scan(self, *paths):
        return subprocess.run([sys.executable, "-I", SCAN, *paths], capture_output=True, text=True)

    def test_source_tree_and_docs_have_no_secrets(self):
        r = self.scan(ROOT, os.path.join(ROOT, "..", "docs", "ctal"))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_export_contains_no_secrets_and_scanner_detects_planted_ones(self):
        w = World()
        w.run()
        z = build_export(w.ledger(), w.exp_s, w.public, actor="t", correlation_id="c", clock=w.clock)
        d = tempfile.mkdtemp()
        p = os.path.join(d, "e.zip")
        with open(p, "wb") as f:
            f.write(z)
        self.assertEqual(self.scan(p).returncode, 0)
        bad = os.path.join(d, "bad.txt")
        with open(bad, "wb") as f:
            f.write(b"-----BEGIN PRIVATE KEY-----\nabc\n" + b"ctal_" + b"A" * 40)
        r = self.scan(bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("private_key_block", r.stdout)
        self.assertIn("ctal_api_key", r.stdout)

    def test_signer_repr_and_files_do_not_expose_key(self):
        w = World()
        self.assertNotIn("PRIVATE", repr(w.env_s))
        d = tempfile.mkdtemp()
        path = os.path.join(d, "k.pem")
        w.env_s.save_pem(path)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            w.env_s.save_pem(path)  # never silently overwrite a key

    def test_production_refuses_dev_keys_and_missing_keys(self):
        d = tempfile.mkdtemp()
        base = {"CTAL_DB": os.path.join(d, "x.db"), "CTAL_ENVELOPE_KEY": os.path.join(d, "e.pem"),
                "CTAL_EXPORT_KEY": os.path.join(d, "x.pem")}
        with self.assertRaises(RuntimeError):                      # default dev-* key ids
            build_from_env({**base, "CTAL_ENV": "production"})
        with self.assertRaises(RuntimeError):                      # production id but key file absent => never auto-generate
            build_from_env({**base, "CTAL_ENV": "production", "CTAL_ENVELOPE_KEY_ID": "prod-e1", "CTAL_EXPORT_KEY_ID": "prod-x1"})
        gate, xs, public = build_from_env({**base, "CTAL_ENV": "development"})     # dev generates with dev- ids
        self.assertTrue(gate.signer.key_id.startswith("dev-"))
        os.chmod(base["CTAL_ENVELOPE_KEY"], 0o644)
        with self.assertRaises(RuntimeError):
            load_signer(base["CTAL_ENVELOPE_KEY"], "prod-e1", "production")  # permissions too open
        os.chmod(base["CTAL_ENVELOPE_KEY"], 0o600)
        s = load_signer(base["CTAL_ENVELOPE_KEY"], "prod-e1", "production")
        self.assertEqual(s.public_raw(), gate.signer.public_raw())


if __name__ == "__main__":
    unittest.main()
