"""AT-09 (store level), AT-11 chain integrity, AT-13 policy versions, AT-14 migrations/backup."""
import os
import shutil
import sqlite3
import unittest

from ctal.canon import digest_obj
from ctal.store import Store, TenantAccessError, TenantLedger, event_hash
from ctal.tests.helpers import POLICY, World


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        for i in range(3):
            self.w.run(idem="i%d" % i, content=b"doc %d" % i)
        self.w.run(tenant="globex", idem="g0")

    def test_at09_tenant_scoping_everywhere(self):
        a, g = self.w.ledger("acme"), self.w.ledger("globex")
        env_a = a.all_envelopes()[0]
        self.assertIsNone(g.get_envelope(env_a["envelope_id"]))
        self.assertTrue(all(e["tenant_id"] == "acme" for e in a.events(limit=500)))
        self.assertTrue(all(e["tenant_id"] == "globex" for e in g.events(limit=500)))
        self.assertEqual(g.events(subject_digest=env_a["subject"]["digest"]), [])
        self.assertEqual(g.events(correlation_id="corr-i0"), [])
        self.assertTrue(all(e["tenant_id"] == "globex" for e in g.all_events()))
        self.assertEqual(len(g.protected_actions()), 1)
        conn = self.w.store.connect()
        try:
            with self.assertRaises(TenantAccessError):
                g.put_envelope(conn, env_a)
        finally:
            conn.close()
        with self.assertRaises(TenantAccessError):
            TenantLedger(self.w.store, "")
        self.assertTrue(a.verify_chain()["ok"] and g.verify_chain()["ok"])

    def test_search_filters(self):
        led = self.w.ledger()
        self.w.run(content=b"Ignore previous instructions", idem="x")
        self.assertEqual(len(led.events(event_type="assurance_envelope_signed")), 4)
        self.assertEqual(len(led.events(outcome="BLOCK", event_type="assurance_envelope_signed")), 1)
        self.assertEqual(len(led.events(reason_code="AQPD_REJECT")), 1)
        self.assertEqual(len(led.events(policy_version=1, event_type="assessment_completed")), 4)
        self.assertEqual(led.events(policy_version=2), [])
        self.assertEqual(len(led.events(from_time="2026-06-01T12:00:00Z", to_time="2026-06-01T12:00:00Z", limit=2)), 2)
        self.assertEqual(led.events(from_time="2030-01-01T00:00:00Z"), [])
        self.assertEqual(len(led.events(limit=3, offset=1)), 3)

    def test_event_triggers_block_update_delete(self):
        c = self.w.store.connect()
        for sql in ("UPDATE events SET outcome='PROCEED'", "DELETE FROM events", "UPDATE envelopes SET outcome='PROCEED'",
                    "DELETE FROM envelopes", "UPDATE policies SET digest='x'", "DELETE FROM policies"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                c.execute(sql)
        c.close()

    def _tamper(self, fn):
        """Simulate a DB administrator who drops the triggers, edits history, and leaves hashes alone."""
        c = self.w.store.connect()
        c.execute("DROP TRIGGER events_no_update")
        c.execute("DROP TRIGGER events_no_delete")
        fn(c)
        c.close()

    def test_at11_privileged_edits_are_detected_by_chain(self):
        self._tamper(lambda c: c.execute("UPDATE events SET outcome='PROCEED' WHERE tenant_id='acme' AND seq=5"))
        self.assertEqual(self.w.ledger().verify_chain()["broken_at_seq"], 5)

    def test_at11_deletion_and_reorder_detected(self):
        self._tamper(lambda c: c.execute("DELETE FROM events WHERE tenant_id='acme' AND seq=3"))
        self.assertFalse(self.w.ledger().verify_chain()["ok"])
        w2 = World()
        w2.run()
        w2.run(idem="k2")
        c = w2.store.connect()
        c.execute("DROP TRIGGER events_no_update")
        c.execute("UPDATE events SET seq=-1 WHERE tenant_id='acme' AND seq=1")
        c.execute("UPDATE events SET seq=1 WHERE tenant_id='acme' AND seq=2")
        c.execute("UPDATE events SET seq=2 WHERE tenant_id='acme' AND seq=-1")
        c.close()
        self.assertFalse(w2.ledger().verify_chain()["ok"])

    def test_known_limit_full_rewrite_with_recomputed_hashes_is_not_detected_by_chain_alone(self):
        """Documented limit: only a signed checkpoint held outside the DB exposes this."""
        def rewrite(c):
            rows = c.execute("SELECT * FROM events WHERE tenant_id='acme' ORDER BY seq").fetchall()
            prev = "0" * 64
            for r in rows:
                d = dict(r)
                d["prev_hash"] = prev
                if d["seq"] == 5:
                    d["outcome"] = "PROCEED"
                import json
                d["reason_codes"], d["payload"] = json.loads(d["reason_codes"]), json.loads(d["payload"])
                d["hash"] = prev = event_hash(d)
                c.execute("UPDATE events SET outcome=?, prev_hash=?, hash=? WHERE tenant_id='acme' AND seq=?",
                          (d["outcome"], d["prev_hash"], d["hash"], d["seq"]))
        self._tamper(rewrite)
        self.assertTrue(self.w.ledger().verify_chain()["ok"])

    def test_at13_policy_versions_immutable_and_decisions_pinned(self):
        led = self.w.ledger()
        env1 = led.all_envelopes()[0]
        v1 = led.get_policy("pol", 1)
        r = led.publish_policy("pol", {**POLICY, "reject_patterns": ["doc 0"]}, "admin", "c")
        self.assertEqual(r["version"], 2)
        self.assertNotEqual(r["digest"], v1["digest"])
        self.assertEqual(led.get_policy("pol", 1)["digest"], v1["digest"])
        self.assertEqual(led.get_policy("pol")["version"], 2)
        self.assertEqual(v1["digest"], digest_obj(v1["body"]))
        self.assertEqual(env1["aqpd"]["policy_version"], 1)
        # new decision uses v2 and rejects content v1 accepted; old envelope still says v1 and still verifies
        new = self.w.run(content=b"doc 0", idem="after")["envelope"]
        self.assertEqual((new["aqpd"]["policy_version"], new["aqpd"]["status"]), (2, "REJECT"))
        self.assertNotEqual(new["policy_bundle_digest"], env1["policy_bundle_digest"])
        types = [e["event_type"] for e in led.events(event_type=None, limit=500) if e["event_type"].startswith("policy_")]
        self.assertEqual(types, ["policy_created", "policy_version_published"])
        self.assertEqual(self.w.ledger("globex").get_policy("pol")["version"], 1)  # tenants have independent registries

    def test_at14_migration_rollback_and_reapply(self):
        s = Store(os.path.join(self.w.tmp, "m.db"))
        self.assertEqual(s.migrate_up(), ["0001_init", "0002_online"])
        self.assertEqual(s.migrate_up(), [])
        self.assertEqual(s.schema_version(), "0002_online")
        s.migrate_down("0002_online")
        self.assertEqual(s.schema_version(), "0001_init")
        self.assertEqual(s.migrate_up(), ["0002_online"])
        s.migrate_down("0002_online")
        s.migrate_down("0001_init")
        c = s.connect()
        self.assertEqual(c.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('events','policies','api_keys')").fetchone()[0], 0)
        c.close()
        self.assertEqual(s.migrate_up(), ["0001_init", "0002_online"])

    def test_at14_backup_restore_preserves_chain(self):
        bk = os.path.join(self.w.tmp, "backup.db")
        self.w.store.backup_to(bk)
        restored = Store(os.path.join(self.w.tmp, "restored.db"))
        shutil.copy(bk, restored.path)
        led = TenantLedger(restored, "acme")
        orig = self.w.ledger()
        self.assertEqual(led.verify_chain(), orig.verify_chain())
        self.assertEqual(led.all_envelopes(), orig.all_envelopes())
        self.assertIsNotNone(restored.authenticate(self.w.keys["acme"]))

    def test_api_keys_are_hashed_and_revocable(self):
        c = self.w.store.connect()
        stored = [r[0] for r in c.execute("SELECT key_hash FROM api_keys")]
        c.close()
        self.assertNotIn(self.w.keys["acme"], stored)
        self.assertIsNone(self.w.store.authenticate("ctal_nope"))
        self.assertIsNone(self.w.store.authenticate(None))
        self.w.store.revoke_api_key(self.w.keys["acme"])
        self.assertIsNone(self.w.store.authenticate(self.w.keys["acme"]))


if __name__ == "__main__":
    unittest.main()
