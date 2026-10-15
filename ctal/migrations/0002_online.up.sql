CREATE TABLE revocations (
  tenant_id TEXT NOT NULL, license_id TEXT NOT NULL, reason TEXT NOT NULL, revoked_at TEXT NOT NULL,
  revoked_by TEXT NOT NULL, PRIMARY KEY (tenant_id, license_id));
CREATE TRIGGER revocations_no_update BEFORE UPDATE ON revocations BEGIN SELECT RAISE(ABORT, 'revocations are permanent'); END;
CREATE TRIGGER revocations_no_delete BEFORE DELETE ON revocations BEGIN SELECT RAISE(ABORT, 'revocations are permanent'); END;

CREATE TABLE activations (
  tenant_id TEXT NOT NULL, license_id TEXT NOT NULL, instance_id TEXT NOT NULL, first_seen TEXT NOT NULL,
  PRIMARY KEY (tenant_id, license_id, instance_id));

CREATE TABLE regression_cases (
  tenant_id TEXT NOT NULL, case_id TEXT NOT NULL, status TEXT NOT NULL, content_b64 TEXT NOT NULL,
  media_type TEXT NOT NULL, content_digest TEXT NOT NULL, expected_status TEXT NOT NULL, incident_ref TEXT NOT NULL,
  provenance TEXT NOT NULL, proposed_by TEXT NOT NULL, proposed_by_principal TEXT NOT NULL, proposed_at TEXT NOT NULL,
  decided_by TEXT, decided_at TEXT, decision_note TEXT, PRIMARY KEY (tenant_id, case_id));
CREATE TRIGGER regression_cases_frozen BEFORE UPDATE ON regression_cases
WHEN OLD.content_b64 != NEW.content_b64 OR OLD.expected_status != NEW.expected_status OR OLD.content_digest != NEW.content_digest
  OR OLD.proposed_by != NEW.proposed_by OR OLD.status != 'proposed' OR NEW.status NOT IN ('approved','rejected')
BEGIN SELECT RAISE(ABORT, 'regression case content is frozen; only proposed -> approved|rejected is allowed'); END;
CREATE TRIGGER regression_cases_no_delete BEFORE DELETE ON regression_cases BEGIN SELECT RAISE(ABORT, 'regression cases are permanent'); END;
