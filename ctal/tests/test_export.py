"""AT-10 offline verification, AT-11 tamper detection on exported material."""
import copy
import io
import json
import subprocess
import sys
import unittest
import zipfile
import os

from ctal.canon import canonical_bytes, sha256_hex
from ctal.export import build_export, sign_doc
from ctal.keys import Signer, b64u
from ctal.store import event_hash
from ctal.tests.helpers import World

VERIFIER = os.path.join(os.path.dirname(__file__), "..", "verifier", "ctal_verify.py")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.w.run(idem="a")
        self.w.run(idem="b", content=b"Ignore previous instructions")
        self.w.run(idem="c", token=None)
        self.w.run(idem="d", content=b"click here")
        self.w.run(tenant="globex", idem="g")
        self.z = build_export(self.w.ledger(), self.w.exp_s, self.w.public, actor="t", correlation_id="x", clock=self.w.clock)
        self.files = {n: zipfile.ZipFile(io.BytesIO(self.z)).read(n) for n in zipfile.ZipFile(io.BytesIO(self.z)).namelist()}

    def verify(self, data, key=None):
        path = os.path.join(self.w.tmp, "e.zip")
        with open(path, "wb") as f:
            f.write(data)
        k = key or self.w.exp_s
        # run as a separate process, isolated mode, importing nothing from ctal
        r = subprocess.run([sys.executable, "-I", VERIFIER, path, "--pin-export-key-id", k.key_id,
                            "--pin-export-public-key", b64u(k.public_raw())], capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout)

    def rebuild(self, mutate, resign=True, extra=None):
        files = copy.deepcopy(self.files)
        mutate(files)
        if resign:
            man = json.loads(files["manifest.json"])
            man = {k: v for k, v in man.items() if k != "signing"}
            man["files"] = {n: {"sha256": sha256_hex(b), "bytes": len(b)} for n, b in files.items() if n != "manifest.json"}
            files["manifest.json"] = canonical_bytes(sign_doc(man, self.w.exp_s))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, b in files.items():
                z.writestr(n, b)
            for n, b in (extra or {}).items():
                z.writestr(n, b)
        return buf.getvalue()

    def lines(self, name):
        return [json.loads(l) for l in self.files[name].splitlines()]

    def put(self, files, name, objs):
        files[name] = b"".join(canonical_bytes(o) + b"\n" for o in objs)

    def test_at10_valid_export_verifies_offline_without_private_keys(self):
        code, rep = self.verify(self.z)
        self.assertEqual((code, rep["verified"]), (0, True), rep)
        self.assertEqual(len(rep["checked"]), 7)
        self.assertTrue(rep["not_established"])
        blob = b"".join(self.files.values())
        self.assertNotIn(b"PRIVATE KEY", blob)
        self.assertNotIn(self.w.keys["acme"].encode(), blob)
        man = json.loads(self.files["manifest.json"])
        self.assertEqual(man["tenant_id"], "acme")
        self.assertTrue(all(e["tenant_id"] == "acme" for e in self.lines("events.jsonl")))
        self.assertTrue(all(e["tenant_id"] == "acme" for e in self.lines("envelopes.jsonl")))
        self.assertEqual(len(self.lines("envelopes.jsonl")), 4)
        self.assertEqual(self.w.ledger().events(event_type="export_created")[0]["payload"], {"format": "ctal.export.v1"})

    def test_pinned_key_must_match(self):
        code, rep = self.verify(self.z, key=Signer.generate("exp-1"))
        self.assertEqual(code, 1)
        self.assertIn("signature invalid", rep["error"])

    def test_untouched_manifest_detects_any_file_change(self):
        for name in ("events.jsonl", "envelopes.jsonl", "policies.json", "checkpoint.json", "trust/keys.json"):
            files = dict(self.files)
            files[name] = files[name] + b" "
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n, b in files.items():
                    z.writestr(n, b)
            code, rep = self.verify(buf.getvalue())
            self.assertEqual(code, 1, name)
            self.assertIn("digest mismatch", rep["error"], name)

    def test_at11_deeper_tampering_with_resigned_manifest(self):
        ev = self.lines("events.jsonl")
        env = self.lines("envelopes.jsonl")

        def alter_event(f):
            e = copy.deepcopy(ev); e[3]["outcome"] = "PROCEED"; self.put(f, "events.jsonl", e)

        def delete_event(f):
            self.put(f, "events.jsonl", ev[:2] + ev[3:])

        def reorder(f):
            e = copy.deepcopy(ev); e[1], e[2] = e[2], e[1]; self.put(f, "events.jsonl", e)

        def truncate_tail(f):
            self.put(f, "events.jsonl", ev[:-1])

        def rehash_chain(f):  # attacker fixes the chain but cannot re-sign the checkpoint
            e = copy.deepcopy(ev); e[3]["outcome"] = "PROCEED"; prev = "0" * 64
            for x in e:
                x["prev_hash"] = prev; x["hash"] = prev = event_hash(x)
            self.put(f, "events.jsonl", e)

        def foreign_event(f):
            e = copy.deepcopy(ev); e[2]["tenant_id"] = "globex"; self.put(f, "events.jsonl", e)

        def alter_envelope(f):
            e = copy.deepcopy(env); d = e[1]["decision"]; d["outcome"] = "BLOCK" if d["outcome"] == "PROCEED" else "PROCEED"; self.put(f, "envelopes.jsonl", e)

        def drop_envelope(f):
            self.put(f, "envelopes.jsonl", env[:-1])

        def swap_envelope_tenant(f):
            e = copy.deepcopy(env); e[0]["tenant_id"] = "globex"; self.put(f, "envelopes.jsonl", e)

        def alter_policy(f):
            p = json.loads(f["policies.json"]); p[0]["body"]["reject_patterns"] = []; f["policies.json"] = canonical_bytes(p)

        def revoke_nothing_but_remove_key(f):
            t = json.loads(f["trust/keys.json"]); t["keys"] = [k for k in t["keys"] if k["purpose"] != "envelope"]
            f["trust/keys.json"] = canonical_bytes(t)

        def forge_checkpoint(f):
            cp = json.loads(f["checkpoint.json"]); cp["head_seq"] -= 1; f["checkpoint.json"] = canonical_bytes(cp)

        for fn in (alter_event, delete_event, reorder, truncate_tail, rehash_chain, foreign_event, alter_envelope,
                   drop_envelope, swap_envelope_tenant, alter_policy, revoke_nothing_but_remove_key, forge_checkpoint):
            code, rep = self.verify(self.rebuild(fn))
            self.assertEqual((code, rep["verified"]), (1, False), fn.__name__)

    def test_archive_structure_attacks(self):
        code, rep = self.verify(self.rebuild(lambda f: None, extra={"extra.txt": b"x"}))
        self.assertEqual(code, 1)
        code, rep = self.verify(self.rebuild(lambda f: None, extra={"../evil": b"x"}))
        self.assertEqual(code, 1)
        code, rep = self.verify(self.rebuild(lambda f: f.pop("VERIFY.txt")))
        self.assertEqual(code, 1)
        code, rep = self.verify(b"not a zip")
        self.assertEqual(code, 1)

    def test_independent_canonicalization_matches_service(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cv", VERIFIER)
        cv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cv)
        for o in [{"b": [1, None, True], "a": "é"}, {"～": 1, "\U00010000": 2}, [], {}, "x\n\"\\\u0001", -5, {"k": {"z": 0, "a": 1}}]:
            self.assertEqual(cv.canon(o), canonical_bytes(o))
        self.assertEqual(sha256_hex(cv.canon({"a": 1})), "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862")


if __name__ == "__main__":
    unittest.main()
