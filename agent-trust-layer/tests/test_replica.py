import shutil, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.replica import Node


class ReplicaTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.nodes = []
        mk = lambda n, role: Node(self.d / f"{n}.db", "s3cret", role=role)
        self.L, self.A, self.B = mk("l", "leader"), mk("a", "follower"), mk("b", "follower")
        self.nodes = [self.L, self.A, self.B]
        for n in self.nodes:
            n.peers = [o.addr for o in self.nodes if o is not n]
        self.L.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
        for i in range(200):
            self.L.execute("INSERT INTO t(v) VALUES(?)", ("x" * 200 + str(i),))

    def tearDown(self):
        for n in self.nodes:
            n.close()
        shutil.rmtree(self.d, ignore_errors=True)

    def corrupt(self, node, page, mode="flip"):
        node._close_conn()
        ps = node.page_size
        with open(node.path, "r+b") as f:
            f.seek(page * ps)
            f.write(b"\x00" * ps if mode == "zero" else bytes(b ^ 0xFF for b in f.read(64)))
            if mode == "flip":
                f.seek(page * ps + 100)
                f.write(b"\xde\xad\xbe\xef")

    def test_replication(self):
        for n in (self.A, self.B):
            self.assertEqual(n.query("SELECT count(*) FROM t"), [(200,)])
            self.assertEqual(n.gen, self.L.gen)

    def test_follower_rejects_writes(self):
        with self.assertRaises(PermissionError):
            self.A.execute("INSERT INTO t(v) VALUES('x')")

    def test_heals_flipped_and_zeroed_pages(self):
        self.assertGreater(len(self.A.hashes), 5)
        self.corrupt(self.A, 3, "flip")
        self.corrupt(self.A, 4, "zero")
        self.assertEqual(sorted(self.A.scrub()), [3, 4])
        self.assertEqual(self.A.heal(), [])
        self.assertEqual(self.A.scrub(), [])
        self.assertTrue(self.A.integrity_ok())
        self.assertEqual(self.A.query("SELECT count(*) FROM t"), [(200,)])

    def test_heals_page_one_and_truncation(self):
        self.corrupt(self.B, 0, "zero")
        n = len(self.B.hashes)
        with open(self.B.path, "r+b") as f:
            f.truncate((n - 3) * self.B.page_size)
        self.assertEqual(self.B.heal(), [])
        self.assertTrue(self.B.integrity_ok())
        self.assertEqual(self.B.query("SELECT count(*) FROM t"), [(200,)])

    def test_leader_heals_from_follower(self):
        self.corrupt(self.L, 2, "flip")
        self.assertEqual(self.L.heal(), [])
        self.assertTrue(self.L.integrity_ok())

    def test_unhealable_when_all_peers_damaged(self):
        for n in (self.L, self.A, self.B):
            self.corrupt(n, 3, "zero")
        self.assertEqual(self.A.heal(), [3])

    def test_lagging_follower_catches_up_with_delta(self):
        peers, self.L.peers = self.L.peers, []
        for i in range(20):
            self.L.execute("INSERT INTO t(v) VALUES('late')")
        self.L.peers = peers
        self.assertLess(self.A.gen, self.L.gen)
        self.A.sync_and_heal()
        self.assertEqual(self.A.gen, self.L.gen)
        self.assertEqual(self.A.query("SELECT count(*) FROM t"), [(220,)])

    def test_fresh_node_bootstraps(self):
        n = Node(self.d / "new.db", "s3cret", peers=[self.L.addr])
        self.nodes.append(n)
        n.sync_and_heal()
        self.assertEqual(n.query("SELECT count(*) FROM t"), [(200,)])

    def test_wrong_secret_rejected(self):
        n = Node(self.d / "evil.db", "wrong", peers=[self.L.addr])
        self.nodes.append(n)
        n.sync_and_heal()
        self.assertEqual(n.gen, 0)


if __name__ == "__main__":
    unittest.main()
