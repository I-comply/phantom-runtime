"""Ledger bake-off: one tamper/replay suite run against every adapter.
Adapter contract (see ATLAdapter): new(), append(tenant, payload), count(tenant), verify(tenant)->bool,
anchor(tenant), tamper(tenant, kind). POM/SAL adapters are not implementable here (their code is not in this repo):
drop a module in bakeoff/ exposing ADAPTER = <class> and add its name to ADAPTERS.
Run: python3 -m unittest bakeoff.suite -v"""
import importlib, shutil, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from atl.gateway import Core
from atl.util import canon

ADAPTERS = ["atl", "pom", "sal"]


class ATLAdapter:
    name = "atl"

    def new(self):
        self.d = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "capabilities.json", self.d / "capabilities.json")
        self.c = Core(self.d)
        return self

    def close(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def append(self, tenant, payload):
        self.c.ident.create_tenant(tenant)
        return self.c.ledger.append(tenant, "bench.event", "bench", payload)

    def count(self, tenant):
        return len(self.c.ledger.events(tenant, 10 ** 9))

    def verify(self, tenant):
        return self.c.verify_all(tenant)["ok"]

    def anchor(self, tenant):
        self.c.anchor(tenant)

    def tamper(self, tenant, kind):
        db = self.c.db.conn()
        db.executescript("DROP TRIGGER IF EXISTS events_no_update; DROP TRIGGER IF EXISTS events_no_delete;")
        if kind == "modify":
            db.execute("UPDATE events SET payload='{\"x\":1}' WHERE tenant_id=? AND seq=2", (tenant,))
        elif kind == "delete_middle":
            db.execute("DELETE FROM events WHERE tenant_id=? AND seq=2", (tenant,))
        elif kind == "truncate_tail":
            db.execute("DELETE FROM events WHERE tenant_id=? AND seq>3", (tenant,))
        elif kind == "swap":
            db.execute("UPDATE events SET seq=-1 WHERE tenant_id=? AND seq=2", (tenant,))
            db.execute("UPDATE events SET seq=2 WHERE tenant_id=? AND seq=3", (tenant,))
            db.execute("UPDATE events SET seq=3 WHERE tenant_id=? AND seq=-1", (tenant,))
        elif kind == "rehash_no_key":  # attacker recomputes hash chain but lacks the MAC key
            from atl.ledger import _body
            from atl.util import sha256
            rows = db.execute("SELECT * FROM events WHERE tenant_id=? ORDER BY seq", (tenant,)).fetchall()
            prev = None
            for r in rows:
                pl = '{"x":1}' if r["seq"] == 2 else r["payload"]
                ph = prev if prev else r["prev_hash"]
                body = dict(_body(r), payload=__import__("json").loads(pl), prev_hash=ph)
                h = sha256(canon(body))
                db.execute("UPDATE events SET payload=?,prev_hash=?,hash=? WHERE tenant_id=? AND seq=?", (pl, ph, h, tenant, r["seq"]))
                prev = h
        else:
            raise ValueError(kind)


def load(name):
    if name == "atl":
        return ATLAdapter
    try:
        return importlib.import_module(f"bakeoff.{name}").ADAPTER
    except ImportError:
        return None


def make_suite(name):
    cls = load(name)

    @unittest.skipIf(cls is None, f"{name} adapter not provided")
    class Suite(unittest.TestCase):
        def setUp(self):
            self.a = cls().new()
            self.addCleanup(self.a.close)
            self.t = "bench"
            for i in range(6):
                self.a.append(self.t, {"i": i})

        def test_clean_ledger_verifies(self):
            self.assertTrue(self.a.verify(self.t))

        def test_modify(self):
            self.a.tamper(self.t, "modify"); self.assertFalse(self.a.verify(self.t))

        def test_delete_middle(self):
            self.a.tamper(self.t, "delete_middle"); self.assertFalse(self.a.verify(self.t))

        def test_truncate_tail_needs_anchor(self):
            self.a.anchor(self.t)
            self.a.tamper(self.t, "truncate_tail"); self.assertFalse(self.a.verify(self.t))

        def test_reorder(self):
            self.a.tamper(self.t, "swap"); self.assertFalse(self.a.verify(self.t))

        def test_rehash_without_key(self):
            self.a.tamper(self.t, "rehash_no_key"); self.assertFalse(self.a.verify(self.t))

        def test_tenant_chains_independent(self):
            self.a.append("other", {"k": 1})
            self.a.tamper(self.t, "modify")
            self.assertTrue(self.a.verify("other"))
    Suite.__name__ = f"Suite_{name}"
    return Suite


for _n in ADAPTERS:
    globals()[f"Suite_{_n}"] = make_suite(_n)

if __name__ == "__main__":
    unittest.main()
