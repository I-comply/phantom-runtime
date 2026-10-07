import json, tempfile, unittest, copy
from atl import groth16, zkid

SKIP = not groth16.AVAILABLE
TOOLS = ["echo", "fs_delete", "fs_read", "fs_write", "hash_text"]
GRANTED = {"echo", "fs_read", "hash_text"}
SECRET = "ab" * 32
CFG, ENV = {"region": "eu", "sandbox": "docker"}, {"API_TOKEN": "tok-live-123"}


@unittest.skipIf(SKIP, "py_ecc not installed")
class ZK(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.zk = zkid.ZKIdentity(cls.dir.name, rounds=7)       # reduced rounds keep tests fast
        cls.mask = zkid.permission_mask(TOOLS, GRANTED.__contains__)
        cls.v = zkid.Verifier(cls.zk)
        cls.v.register("acme", "a1", cls.zk.enroll(SECRET, cls.mask, CFG, ENV))

    def prove(self, tool, nonce, mask=None, secret=SECRET):
        return self.zk.prove(secret, self.mask if mask is None else mask, CFG, ENV, TOOLS, tool, "acme", "a1",
                             nonce.encode())

    def test_valid_and_no_leak(self):
        n = self.v.challenge()
        p = self.prove("fs_read", n)
        self.assertTrue(self.v.assert_identity("acme", "a1", "fs_read", TOOLS, n, p))
        blob = json.dumps(p) + self.zk.enroll(SECRET, self.mask, CFG, ENV)
        for s in (SECRET, "tok-live-123", "docker"):
            self.assertNotIn(s, blob)

    def test_ungranted_tool_unprovable(self):
        with self.assertRaises(zkid.ZKError):
            self.prove("fs_write", self.v.challenge())

    def test_forged_mask_rejected(self):
        n = self.v.challenge()
        forged = self.mask | zkid.tool_selector(TOOLS, "fs_write")
        p = self.prove("fs_write", n, mask=forged)             # valid proof, but for a different commitment
        self.assertFalse(self.v.assert_identity("acme", "a1", "fs_write", TOOLS, n, p))

    def test_wrong_secret_rejected(self):
        n = self.v.challenge()
        self.assertFalse(self.v.assert_identity("acme", "a1", "echo", TOOLS, n, self.prove("echo", n, secret="cd" * 32)))

    def test_replay_and_tool_swap_rejected(self):
        n = self.v.challenge()
        p = self.prove("echo", n)
        self.assertFalse(self.v.assert_identity("acme", "a1", "fs_read", TOOLS, n, p))   # tool swap (nonce consumed)
        n2 = self.v.challenge()
        p2 = self.prove("echo", n2)
        self.assertTrue(self.v.assert_identity("acme", "a1", "echo", TOOLS, n2, p2))
        self.assertFalse(self.v.assert_identity("acme", "a1", "echo", TOOLS, n2, p2))    # replay

    def test_tampered_proof_rejected(self):
        n = self.v.challenge()
        p = copy.deepcopy(self.prove("echo", n))
        p["C"] = p["A"]
        self.assertFalse(self.v.assert_identity("acme", "a1", "echo", TOOLS, n, p))
        self.assertFalse(self.zk.verify("1", TOOLS, "echo", "acme", "a1", b"x", {"A": 1}))

    def test_keys_reload(self):
        z2 = zkid.ZKIdentity(self.dir.name, rounds=7)
        n = self.v.challenge()
        p = self.prove("echo", n)
        self.assertTrue(z2.verify(self.zk.enroll(SECRET, self.mask, CFG, ENV), TOOLS, "echo", "acme", "a1", n.encode(), p))


if __name__ == "__main__":
    unittest.main()
