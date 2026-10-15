import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "supabase"))
from migration_validator import (MigrationBlocked, guarded_execute,  # noqa: E402
                                 split_statements, validate_sql)

BIG = {"events": 5_000_000, "users": 1_000_000, "tiny": 10, "empty": 0}


def rules(sql, counts=BIG, **kw):
    return {(f.rule, f.severity.name) for f in validate_sql(sql, counts, **kw).findings}


class T(unittest.TestCase):
    def test_split_ignores_quotes_comments_dollar(self):
        s = "select ';'; -- x;\n/* ; */ do $$ begin x; end $$; select 1"
        self.assertEqual(len(split_statements(s)), 3)

    def test_drop_column_blocks_nonempty_only(self):
        self.assertIn(("drop-column", "BLOCK"), rules("ALTER TABLE events DROP COLUMN a"))
        self.assertEqual(rules("ALTER TABLE empty DROP COLUMN a"), set())

    def test_drop_table_truncate(self):
        self.assertIn(("drop-table", "BLOCK"), rules("DROP TABLE public.events"))
        self.assertIn(("truncate", "BLOCK"), rules("TRUNCATE TABLE tiny"))

    def test_fk_validating_vs_not_valid(self):
        bad = "ALTER TABLE events ADD CONSTRAINT f FOREIGN KEY (u) REFERENCES users(id)"
        self.assertIn(("add-fk-validating", "BLOCK"), rules(bad))
        self.assertEqual(rules(bad + " NOT VALID"), set())

    def test_small_table_lock_ops_pass(self):
        self.assertEqual(rules("ALTER TABLE tiny ALTER COLUMN a SET NOT NULL")
                         - {("set-not-null", "WARN")}, set())

    def test_set_not_null_big(self):
        self.assertIn(("set-not-null", "BLOCK"),
                      rules("ALTER TABLE events ALTER COLUMN a SET NOT NULL"))

    def test_alter_type(self):
        self.assertIn(("alter-type", "BLOCK"),
                      rules("ALTER TABLE events ALTER COLUMN a TYPE int USING a::int"))

    def test_add_not_null_no_default(self):
        self.assertIn(("add-not-null-no-default", "BLOCK"),
                      rules("ALTER TABLE tiny ADD COLUMN c int NOT NULL"))
        self.assertEqual(rules("ALTER TABLE tiny ADD COLUMN c int NOT NULL DEFAULT 0"), set())

    def test_volatile_default(self):
        self.assertIn(("add-column-volatile-default", "BLOCK"),
                      rules("ALTER TABLE events ADD COLUMN c uuid DEFAULT gen_random_uuid()"))
        self.assertEqual(rules("ALTER TABLE events ADD COLUMN c int DEFAULT 0"), set())

    def test_index(self):
        self.assertIn(("index-not-concurrent", "BLOCK"),
                      rules("CREATE INDEX i ON events(a)"))
        self.assertEqual(rules("CREATE INDEX CONCURRENTLY i ON events(a)"), set())

    def test_new_table_is_empty(self):
        sql = "CREATE TABLE t(a int); CREATE INDEX i ON t(a); ALTER TABLE t DROP COLUMN a"
        self.assertEqual(rules(sql, {}), set())

    def test_unknown_fails_closed(self):
        self.assertIn(("drop-column", "BLOCK"), rules("ALTER TABLE mystery DROP COLUMN a", {}))
        self.assertEqual(rules("ALTER TABLE mystery DROP COLUMN a", {}, unknown_table_blocks=False), set())

    def test_delete_update_without_where(self):
        self.assertIn(("delete-without-where", "BLOCK"), rules("DELETE FROM events"))
        self.assertEqual(rules("DELETE FROM events WHERE id=1"), set())
        self.assertIn(("unbounded-update", "BLOCK"), rules("UPDATE events SET a=1"))

    def test_string_literal_not_parsed(self):
        self.assertEqual(rules("INSERT INTO events(a) VALUES ('DROP TABLE events')"), set())

    def test_guard(self):
        ran = []
        with self.assertRaises(MigrationBlocked):
            guarded_execute("DROP TABLE events", ran.append, BIG)
        self.assertEqual(ran, [])
        guarded_execute("ALTER TABLE events ADD COLUMN c int", ran.append, BIG)
        self.assertEqual(len(ran), 1)

    def test_existing_migrations_on_empty_db(self):
        base = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations")
        for fn in sorted(os.listdir(base)):
            with open(os.path.join(base, fn)) as fh:
                self.assertFalse(validate_sql(fh.read(), {}, unknown_table_blocks=False).blocked, fn)


if __name__ == "__main__":
    unittest.main()
