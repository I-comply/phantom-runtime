CREATE TABLE events (
  tenant_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE, schema_version TEXT NOT NULL,
  event_type TEXT NOT NULL, event_time TEXT NOT NULL, actor TEXT NOT NULL, correlation_id TEXT NOT NULL,
  subject_digest TEXT, policy_id TEXT, policy_version INTEGER, release_digest TEXT, outcome TEXT,
  reason_codes TEXT NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL,
  PRIMARY KEY (tenant_id, seq));
CREATE INDEX events_tenant_time ON events (tenant_id, event_time);
CREATE INDEX events_tenant_subject ON events (tenant_id, subject_digest);
CREATE INDEX events_tenant_corr ON events (tenant_id, correlation_id);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE policies (
  tenant_id TEXT NOT NULL, policy_id TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL,
  body TEXT NOT NULL, published_at TEXT NOT NULL, published_by TEXT NOT NULL,
  PRIMARY KEY (tenant_id, policy_id, version));
CREATE TRIGGER policies_no_update BEFORE UPDATE ON policies BEGIN SELECT RAISE(ABORT, 'policy versions are immutable'); END;
CREATE TRIGGER policies_no_delete BEFORE DELETE ON policies BEGIN SELECT RAISE(ABORT, 'policy versions are immutable'); END;

CREATE TABLE envelopes (
  tenant_id TEXT NOT NULL, envelope_id TEXT NOT NULL, subject_digest TEXT NOT NULL, outcome TEXT NOT NULL,
  issued_at TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (tenant_id, envelope_id));
CREATE TRIGGER envelopes_no_update BEFORE UPDATE ON envelopes BEGIN SELECT RAISE(ABORT, 'envelopes are immutable'); END;
CREATE TRIGGER envelopes_no_delete BEFORE DELETE ON envelopes BEGIN SELECT RAISE(ABORT, 'envelopes are immutable'); END;

CREATE TABLE idempotency (
  tenant_id TEXT NOT NULL, idem_key TEXT NOT NULL, request_digest TEXT NOT NULL, state TEXT NOT NULL,
  envelope_id TEXT, started_at TEXT NOT NULL, PRIMARY KEY (tenant_id, idem_key));

CREATE TABLE protected_actions (
  tenant_id TEXT NOT NULL, idem_key TEXT NOT NULL, envelope_id TEXT NOT NULL, action TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY (tenant_id, idem_key));

CREATE TABLE checkpoints (
  tenant_id TEXT NOT NULL, id INTEGER NOT NULL, head_seq INTEGER NOT NULL, head_hash TEXT NOT NULL,
  body TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (tenant_id, id));
CREATE TRIGGER checkpoints_no_update BEFORE UPDATE ON checkpoints BEGIN SELECT RAISE(ABORT, 'checkpoints are immutable'); END;
CREATE TRIGGER checkpoints_no_delete BEFORE DELETE ON checkpoints BEGIN SELECT RAISE(ABORT, 'checkpoints are immutable'); END;

CREATE TABLE api_keys (
  key_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, role TEXT NOT NULL, label TEXT NOT NULL,
  created_at TEXT NOT NULL, revoked_at TEXT);
