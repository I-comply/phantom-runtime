import json, os, shutil, sqlite3, sys, tempfile, textwrap, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from replaycheck.cli import main, run, build_parser

CLEAN = """
def initial():
    return {"balance": 0, "count": 0, "names": []}

def apply(state, ev):
    s = {"balance": state["balance"], "count": state["count"] + 1, "names": list(state["names"])}
    if ev["type"] == "deposit":
        s["balance"] += ev["amount"]
    elif ev["type"] == "name":
        s["names"] = sorted(set(s["names"]) | {ev["name"]})
    return s
"""
TIME_BUG = CLEAN.replace("import", "import") .replace("def initial", "import time\ndef initial", 1).replace(
    "    return s\n", "    s['at'] = time.time()\n    return s\n")
UUID_BUG = CLEAN.replace("def initial", "import uuid\ndef initial", 1).replace(
    "    return s\n", "    s['id'] = str(uuid.uuid4())\n    return s\n")
SET_BUG = CLEAN.replace("    return s\n", "    s['joined'] = ','.join(set(s['names']))\n    return s\n")
FLOAT_BUG = """
VALS = {"a": 1e16, "b": 1.0, "c": -1e16, "d": 0.1, "e": 0.2, "f": 0.3, "g": 2.5, "h": 1e-3}
def initial():
    return {"n": 0, "total": 0.0}
def apply(state, ev):
    t = 0.0
    for k in set(VALS):  # accumulation order depends on string hash seed (sum() is compensated on 3.12+)
        t += VALS[k]
    return {"n": state["n"] + 1, "total": t}
"""
MUTATE_BUG = CLEAN.replace("def apply(state, ev):", "def apply(state, ev):\n    ev['seen'] = True")
RAISE_BUG = CLEAN.replace("def apply(state, ev):", "def apply(state, ev):\n    if ev.get('boom'): raise KeyError('boom')")
SET_STATE = CLEAN.replace("    return s\n", "    s['tags'] = {1, 2}\n    return s\n")

EVENTS = [{"type": "deposit", "amount": 5}, {"type": "name", "name": "n1"}, {"type": "name", "name": "n2"},
          {"type": "name", "name": "n3"}, {"type": "name", "name": "n4"}, {"type": "name", "name": "n5"},
          {"type": "name", "name": "n6"}, {"type": "deposit", "amount": 7}, {"type": "name", "name": "n7"},
          {"type": "name", "name": "n8"}]


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def w(self, name, text):
        p = self.d / name
        p.write_text(textwrap.dedent(text))
        return str(p)

    def events(self, evs=EVENTS):
        return self.w("events.jsonl", "".join(json.dumps(e) + "\n" for e in evs))

    def go(self, reducer_src, *extra, evs=EVENTS):
        argv = ["run", "--store", self.events(evs), "--reducer", self.w("red.py", reducer_src), "--format", "json"] + list(extra)
        return run(build_parser().parse_args(argv))


class TestDeterminism(Base):
    def test_clean_passes(self):
        rep = self.go(CLEAN)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["findings"], [])

    def test_clock_bug_points_at_first_event(self):
        f = self.go(TIME_BUG)["findings"][0]
        self.assertEqual((f["check"], f["event_index"]), ("determinism", 1))
        self.assertIn("$.at", f["detail"])

    def test_uuid_bug(self):
        f = self.go(UUID_BUG)["findings"][0]
        self.assertEqual((f["check"], f["event_index"]), ("determinism", 1))

    def test_set_order_bug(self):
        rep = self.go(SET_BUG, "--runs", "4")
        f = rep["findings"][0]
        self.assertFalse(rep["ok"])
        self.assertEqual(f["check"], "determinism")
        self.assertIn("joined", f["detail"])

    def test_float_sum_order_bug(self):
        f = self.go(FLOAT_BUG, "--runs", "6")["findings"][0]
        self.assertEqual(f["check"], "determinism")
        self.assertIn("total", f["detail"])

    def test_event_mutation(self):
        f = self.go(MUTATE_BUG)["findings"][0]
        self.assertEqual((f["check"], f["event_index"]), ("event-mutation", 1))

    def test_reducer_exception_reported_with_event(self):
        evs = EVENTS[:3] + [{"type": "deposit", "amount": 1, "boom": True}]
        f = self.go(RAISE_BUG, evs=evs)["findings"][0]
        self.assertEqual((f["check"], f["event_index"]), ("reducer", 4))

    def test_non_json_state(self):
        f = self.go(SET_STATE)["findings"][0]
        self.assertEqual(f["check"], "state-type")


class TestSnapshots(Base):
    def snaps(self, mutate_at=None):
        import importlib.util
        src = self.w("good.py", CLEAN)
        spec = importlib.util.spec_from_file_location("good", src)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        s, lines = m.initial(), []
        for i, ev in enumerate(EVENTS, 1):
            s = m.apply(s, ev)
            if i % 3 == 0:
                st = dict(s)
                if i == mutate_at:
                    st["balance"] += 1
                lines.append(json.dumps({"seq": i, "state": st}))
        return self.w("snaps.jsonl", "\n".join(lines) + "\n")

    def test_good_snapshots_pass(self):
        self.assertTrue(self.go(CLEAN, "--snapshots", self.snaps())["ok"])

    def test_bad_snapshot_detected(self):
        f = self.go(CLEAN, "--snapshots", self.snaps(mutate_at=6))["findings"][0]
        self.assertEqual((f["check"], f["event_index"]), ("snapshot", 6))
        self.assertIn("balance", f["detail"])

    def test_sqlite_snapshots(self):
        db = str(self.d / "s.db")
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE snapshots(seq INTEGER, state TEXT)")
        c.execute("INSERT INTO snapshots VALUES(1, ?)", (json.dumps({"balance": 5, "count": 1, "names": []}),))
        c.commit(); c.close()
        self.assertTrue(self.go(CLEAN, "--snapshots", db)["ok"])


class TestProjection(Base):
    PROJ = """
    def rebuild(events):
        return {"deposits": sum(e["amount"] for e in events if e["type"] == "deposit"),
                "names": len([e for e in events if e["type"] == "name"])}
    """

    def test_matching_live_projection(self):
        live = self.w("live.json", json.dumps({"deposits": 12, "names": 8}))
        self.assertTrue(self.go(CLEAN, "--projection", self.w("proj.py", self.PROJ), "--live", live)["ok"])

    def test_stale_projection(self):
        live = self.w("live.json", json.dumps({"deposits": 5, "names": 8}))
        f = self.go(CLEAN, "--projection", self.w("proj.py", self.PROJ), "--live", live)["findings"][0]
        self.assertEqual(f["check"], "projection")
        self.assertIn("deposits", f["detail"])

    def test_sqlite_live_query(self):
        db = str(self.d / "live.db")
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE t(k TEXT, v INTEGER)")
        c.executemany("INSERT INTO t VALUES(?,?)", [("deposits", 12), ("names", 8)])
        c.commit(); c.close()
        proj = self.w("proj2.py", """
        def rebuild(events):
            return {"deposits": sum(e["amount"] for e in events if e["type"] == "deposit"),
                    "names": len([e for e in events if e["type"] == "name"])}
        def normalize_live(rows):
            return {k: v for k, v in rows}
        """)
        self.assertTrue(self.go(CLEAN, "--projection", proj, "--live", db, "--live-query", "SELECT k, v FROM t")["ok"])


class TestUpcast(Base):
    def test_idempotent_upcast_passes(self):
        up = self.w("up.py", """
        def upcast(e):
            e = dict(e); e.setdefault("v", 2); return e
        def validate(e):
            return [] if e.get("v") == 2 else ["bad v"]
        """)
        self.assertTrue(self.go(CLEAN, "--upcast", up)["ok"])

    def test_non_idempotent_upcast(self):
        up = self.w("up.py", """
        def upcast(e):
            e = dict(e); e["v"] = e.get("v", 0) + 1; return e
        """)
        f = self.go(CLEAN, "--upcast", up)["findings"][0]
        self.assertEqual((f["check"], f["event_index"]), ("upcast", 1))

    def test_validation_failure(self):
        up = self.w("up.py", """
        def upcast(e):
            return dict(e)
        def validate(e):
            return ["missing v"]
        """)
        self.assertIn("missing v", self.go(CLEAN, "--upcast", up)["findings"][0]["detail"])


class TestStoresAndCli(Base):
    def test_sqlite_store_payload_column(self):
        db = str(self.d / "ev.db")
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, payload TEXT)")
        c.executemany("INSERT INTO events(payload) VALUES(?)", [(json.dumps(e),) for e in EVENTS])
        c.commit(); c.close()
        rep = run(build_parser().parse_args(["run", "--store", db, "--reducer", self.w("r.py", CLEAN)]))
        self.assertEqual(rep["events"], len(EVENTS))
        self.assertTrue(rep["ok"])

    def test_exit_codes(self):
        ev, ok, bad = self.events(), self.w("ok.py", CLEAN), self.w("bad.py", TIME_BUG)
        self.assertEqual(main(["run", "--store", ev, "--reducer", ok]), 0)
        self.assertEqual(main(["run", "--store", ev, "--reducer", bad]), 1)
        self.assertEqual(main(["run", "--store", str(self.d / "nope"), "--reducer", ok]), 2)

    def test_reducer_missing_functions(self):
        with self.assertRaises(SystemExit):
            main(["run", "--store", self.events(), "--reducer", self.w("x.py", "x = 1\n")])

    def test_runs_must_be_at_least_two(self):
        with self.assertRaises(SystemExit):
            self.go(CLEAN, "--runs", "1")


if __name__ == "__main__":
    unittest.main()
