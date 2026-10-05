import sqlite3, threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants(tenant_id TEXT PRIMARY KEY, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS principals(
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
  principal_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('agent','approver')),
  key_version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active','revoked')),
  not_before INTEGER NOT NULL,
  expires_at INTEGER,
  revoked_at INTEGER,
  PRIMARY KEY(tenant_id, principal_id, kind));
CREATE TABLE IF NOT EXISTS nonces(tenant_id TEXT NOT NULL, nonce TEXT NOT NULL, expires INTEGER NOT NULL, PRIMARY KEY(tenant_id, nonce));
CREATE INDEX IF NOT EXISTS nonces_exp ON nonces(expires);
CREATE TABLE IF NOT EXISTS requests(tenant_id TEXT NOT NULL, idem_key TEXT NOT NULL, digest TEXT NOT NULL, response TEXT, PRIMARY KEY(tenant_id, idem_key));
CREATE TABLE IF NOT EXISTS approvals_used(k TEXT PRIMARY KEY, used INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rate(k TEXT NOT NULL, bucket INTEGER NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(k, bucket));
CREATE TABLE IF NOT EXISTS events(
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
  seq INTEGER NOT NULL,
  event_id TEXT NOT NULL UNIQUE,
  ts INTEGER NOT NULL,
  type TEXT NOT NULL,
  actor TEXT NOT NULL,
  correlation_id TEXT,
  causation_id TEXT,
  idempotency_key TEXT,
  payload TEXT NOT NULL,
  evidence TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL,
  mac TEXT NOT NULL,
  PRIMARY KEY(tenant_id, seq));
CREATE UNIQUE INDEX IF NOT EXISTS events_idem ON events(tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS events_corr ON events(tenant_id, correlation_id);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'ledger is append-only'); END;
"""


class DB:
    def __init__(self, path):
        self.path = str(path)
        self._l = threading.local()
        c = self.conn()
        c.executescript(SCHEMA)
        if "master_version" not in [r["name"] for r in c.execute("PRAGMA table_info(principals)")]:
            c.execute("ALTER TABLE principals ADD COLUMN master_version INTEGER NOT NULL DEFAULT 1")

    def conn(self):
        c = getattr(self._l, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=10000")
            self._l.c = c
        return c
