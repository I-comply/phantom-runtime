"""SQLite persistence: migrations, tenant-bound ledger, policy registry, idempotency, API keys.

Every data access goes through ``TenantLedger``, which is constructed from an
*authenticated* tenant and puts ``tenant_id = ?`` in every statement. Only API-key
lookup and migrations are tenant-agnostic. Events are per-tenant hash chains:
hash = sha256(canon(event incl. prev_hash)). Triggers reject UPDATE/DELETE on
events, policies, envelopes and checkpoints. These controls detect accidental or
naive modification; a database administrator who can drop triggers and rewrite
the file can still rewrite history, which signed checkpoints held elsewhere
(exports) are meant to expose. See docs/ctal/threat-model.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from .canon import canonical_bytes, digest_obj, sha256_hex
from .contracts import EVENT_TYPES
from .timeutil import fmt_ts, now_utc, parse_ts

EVENT_SCHEMA = "ctal.event.v1"
GENESIS = "0" * 64
ROLES = {"gate": {"gate"}, "auditor": {"read", "export"}, "reviewer": {"read", "propose"},
         "admin": {"gate", "read", "export", "propose", "admin"}}
IN_PROGRESS_LEASE_SECONDS = 60
_MIG_DIR = os.path.join(os.path.dirname(__file__), "migrations")


class TenantAccessError(Exception):
    pass


@dataclass
class AuthContext:
    tenant_id: str
    role: str
    label: str
    principal: str = ""     # stable id of the API key (hash prefix); never the secret

    def allows(self, perm: str) -> bool:
        return perm in ROLES.get(self.role, set())


def event_hash(ev: dict) -> str:
    return sha256_hex(canonical_bytes({k: v for k, v in ev.items() if k != "hash"}))


class Store:
    def __init__(self, path: str, clock: Callable = now_utc):
        self.path, self.clock = path, clock

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def tx(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            c.close()

    # ---- migrations (additive, reversible) ----
    def migrate_up(self) -> List[str]:
        applied = []
        with self.tx() as c:
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
            for f in sorted(x for x in os.listdir(_MIG_DIR) if x.endswith(".up.sql")):
                v = f[:-len(".up.sql")]
                if v in done:
                    continue
                for stmt in _split_sql(_read(os.path.join(_MIG_DIR, f))):
                    c.execute(stmt)
                c.execute("INSERT INTO schema_migrations VALUES (?,?)", (v, fmt_ts(self.clock())))
                applied.append(v)
        return applied

    def migrate_down(self, version: str) -> None:
        with self.tx() as c:
            for stmt in _split_sql(_read(os.path.join(_MIG_DIR, version + ".down.sql"))):
                c.execute(stmt)
            c.execute("DELETE FROM schema_migrations WHERE version=?", (version,))

    def schema_version(self) -> Optional[str]:
        try:
            c = self.connect()
            try:
                r = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
                return r[0]
            finally:
                c.close()
        except sqlite3.Error:
            return None

    def backup_to(self, dest: str) -> None:
        src = self.connect()
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    # ---- API keys (the only tenant-agnostic lookup) ----
    def create_api_key(self, tenant_id: str, role: str, label: str) -> str:
        if role not in ROLES or not tenant_id:
            raise ValueError("BAD_ROLE_OR_TENANT")
        token = "ctal_" + secrets.token_urlsafe(32)
        with self.tx() as c:
            c.execute("INSERT INTO api_keys VALUES (?,?,?,?,?,NULL)",
                      (hashlib.sha256(token.encode()).hexdigest(), tenant_id, role, label, fmt_ts(self.clock())))
        return token

    def revoke_api_key(self, token: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE api_keys SET revoked_at=? WHERE key_hash=?",
                      (fmt_ts(self.clock()), hashlib.sha256(token.encode()).hexdigest()))

    def authenticate(self, token: Optional[str]) -> Optional[AuthContext]:
        if not token or len(token) > 256:
            return None
        c = self.connect()
        try:
            kh = hashlib.sha256(token.encode()).hexdigest()
            r = c.execute("SELECT tenant_id, role, label FROM api_keys WHERE key_hash=? AND revoked_at IS NULL",
                          (kh,)).fetchone()
        finally:
            c.close()
        return AuthContext(r["tenant_id"], r["role"], r["label"], kh[:16]) if r else None

    def for_tenant(self, auth: AuthContext) -> "TenantLedger":
        return TenantLedger(self, auth.tenant_id)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _split_sql(script: str) -> List[str]:
    out, cur = [], ""
    for line in script.splitlines():
        cur += line + "\n"
        s = cur.strip()
        if s.endswith(";") and (not s.upper().startswith("CREATE TRIGGER") or s.upper().endswith("END;")):
            out.append(s)
            cur = ""
    return out


class TenantLedger:
    def __init__(self, store: Store, tenant_id: str):
        if not isinstance(tenant_id, str) or not tenant_id:
            raise TenantAccessError("NO_TENANT")
        self.store, self.tenant_id = store, tenant_id

    # ---- events ----
    def new_event(self, event_type: str, *, actor: str, correlation_id: str, subject_digest=None, policy_id=None,
                  policy_version=None, release_digest=None, outcome=None, reason_codes=None, payload=None) -> dict:
        if event_type not in EVENT_TYPES:
            raise ValueError("UNKNOWN_EVENT_TYPE")
        return {"event_id": "evt-" + uuid.uuid4().hex, "event_type": event_type,
                "event_time": fmt_ts(self.store.clock()), "actor": actor, "correlation_id": correlation_id,
                "subject_digest": subject_digest, "policy_id": policy_id, "policy_version": policy_version,
                "release_digest": release_digest, "outcome": outcome, "reason_codes": list(reason_codes or []),
                "payload": payload or {}}

    def append(self, events: Iterable[dict], conn: Optional[sqlite3.Connection] = None) -> List[dict]:
        if conn is None:
            with self.store.tx() as c:
                return self.append(events, c)
        r = conn.execute("SELECT seq, hash FROM events WHERE tenant_id=? ORDER BY seq DESC LIMIT 1",
                         (self.tenant_id,)).fetchone()
        seq, prev = (r["seq"], r["hash"]) if r else (0, GENESIS)
        out = []
        for e in events:
            seq += 1
            ev = {"tenant_id": self.tenant_id, "seq": seq, "schema_version": EVENT_SCHEMA, **e, "prev_hash": prev}
            ev["hash"] = prev = event_hash(ev)
            conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ev["tenant_id"], ev["seq"], ev["event_id"], ev["schema_version"], ev["event_type"], ev["event_time"],
                 ev["actor"], ev["correlation_id"], ev["subject_digest"], ev["policy_id"], ev["policy_version"],
                 ev["release_digest"], ev["outcome"], json.dumps(ev["reason_codes"]), json.dumps(ev["payload"]),
                 ev["prev_hash"], ev["hash"]))
            out.append(ev)
        return out

    @staticmethod
    def _row_event(r) -> dict:
        d = dict(r)
        d["reason_codes"] = json.loads(d["reason_codes"])
        d["payload"] = json.loads(d["payload"])
        return d

    def events(self, *, from_time=None, to_time=None, outcome=None, policy_version=None, reason_code=None,
               subject_digest=None, correlation_id=None, event_type=None, limit=100, offset=0) -> List[dict]:
        q, a = "SELECT * FROM events WHERE tenant_id=?", [self.tenant_id]
        for col, op, val in (("event_time", ">=", from_time), ("event_time", "<=", to_time), ("outcome", "=", outcome),
                             ("policy_version", "=", policy_version), ("subject_digest", "=", subject_digest),
                             ("correlation_id", "=", correlation_id), ("event_type", "=", event_type)):
            if val is not None:
                q += " AND %s %s ?" % (col, op)
                a.append(val)
        q += " ORDER BY seq"
        limit = max(1, min(int(limit), 500))
        c = self.store.connect()
        try:
            rows = [self._row_event(r) for r in c.execute(q, a)]
        finally:
            c.close()
        if reason_code is not None:
            rows = [e for e in rows if reason_code in e["reason_codes"]]
        return rows[offset:offset + limit]

    def all_events(self) -> List[dict]:
        c = self.store.connect()
        try:
            return [self._row_event(r) for r in
                    c.execute("SELECT * FROM events WHERE tenant_id=? ORDER BY seq", (self.tenant_id,))]
        finally:
            c.close()

    def verify_chain(self) -> Dict[str, object]:
        prev, n = GENESIS, 0
        for ev in self.all_events():
            n += 1
            if ev["seq"] != n or ev["prev_hash"] != prev or ev["tenant_id"] != self.tenant_id \
                    or event_hash(ev) != ev["hash"]:
                return {"ok": False, "broken_at_seq": ev["seq"], "events": n}
            prev = ev["hash"]
        return {"ok": True, "events": n, "head_hash": prev}

    def head(self):
        c = self.store.connect()
        try:
            r = c.execute("SELECT seq, hash FROM events WHERE tenant_id=? ORDER BY seq DESC LIMIT 1",
                          (self.tenant_id,)).fetchone()
        finally:
            c.close()
        return (r["seq"], r["hash"]) if r else (0, GENESIS)

    # ---- policies ----
    def publish_policy(self, policy_id: str, body: dict, actor: str, correlation_id: str) -> dict:
        if not isinstance(body, dict) or not policy_id:
            raise ValueError("BAD_POLICY")
        with self.store.tx() as c:
            r = c.execute("SELECT MAX(version) m FROM policies WHERE tenant_id=? AND policy_id=?",
                          (self.tenant_id, policy_id)).fetchone()
            version = (r["m"] or 0) + 1
            doc = {**body, "policy_id": policy_id, "version": version}
            digest = digest_obj(doc)
            now = fmt_ts(self.store.clock())
            c.execute("INSERT INTO policies VALUES (?,?,?,?,?,?,?)",
                      (self.tenant_id, policy_id, version, digest, canonical_bytes(doc).decode(), now, actor))
            self.append([self.new_event("policy_created" if version == 1 else "policy_version_published",
                                        actor=actor, correlation_id=correlation_id, policy_id=policy_id,
                                        policy_version=version, payload={"policy_digest": digest})], c)
        return {"policy_id": policy_id, "version": version, "digest": digest}

    def get_policy(self, policy_id: str, version: Optional[int] = None) -> Optional[dict]:
        c = self.store.connect()
        try:
            if version is None:
                r = c.execute("SELECT * FROM policies WHERE tenant_id=? AND policy_id=? ORDER BY version DESC LIMIT 1",
                              (self.tenant_id, policy_id)).fetchone()
            else:
                r = c.execute("SELECT * FROM policies WHERE tenant_id=? AND policy_id=? AND version=?",
                              (self.tenant_id, policy_id, version)).fetchone()
        finally:
            c.close()
        if not r:
            return None
        return {"policy_id": r["policy_id"], "version": r["version"], "digest": r["digest"],
                "body": json.loads(r["body"]), "published_at": r["published_at"]}

    def all_policies(self) -> List[dict]:
        c = self.store.connect()
        try:
            return [{"policy_id": r["policy_id"], "version": r["version"], "digest": r["digest"],
                     "body": json.loads(r["body"]), "published_at": r["published_at"]}
                    for r in c.execute("SELECT * FROM policies WHERE tenant_id=? ORDER BY policy_id, version",
                                       (self.tenant_id,))]
        finally:
            c.close()

    # ---- envelopes ----
    def put_envelope(self, conn, env: dict) -> None:
        if env["tenant_id"] != self.tenant_id:
            raise TenantAccessError("ENVELOPE_TENANT_MISMATCH")
        conn.execute("INSERT INTO envelopes VALUES (?,?,?,?,?,?)",
                     (self.tenant_id, env["envelope_id"], env["subject"]["digest"], env["decision"]["outcome"],
                      env["issued_at"], canonical_bytes(env).decode()))

    def get_envelope(self, envelope_id: str) -> Optional[dict]:
        c = self.store.connect()
        try:
            r = c.execute("SELECT body FROM envelopes WHERE tenant_id=? AND envelope_id=?",
                          (self.tenant_id, envelope_id)).fetchone()
        finally:
            c.close()
        return json.loads(r["body"]) if r else None

    def all_envelopes(self) -> List[dict]:
        c = self.store.connect()
        try:
            return [json.loads(r["body"]) for r in
                    c.execute("SELECT body FROM envelopes WHERE tenant_id=? ORDER BY issued_at, envelope_id",
                              (self.tenant_id,))]
        finally:
            c.close()

    # ---- idempotency / protected action ----
    def claim(self, idem_key: str, request_digest: str):
        """Returns ('new'|'replay'|'conflict'|'in_progress', envelope_id|None)."""
        with self.store.tx() as c:
            r = c.execute("SELECT * FROM idempotency WHERE tenant_id=? AND idem_key=?",
                          (self.tenant_id, idem_key)).fetchone()
            now = self.store.clock()
            if r is None:
                c.execute("INSERT INTO idempotency VALUES (?,?,?,?,NULL,?)",
                          (self.tenant_id, idem_key, request_digest, "in_progress", fmt_ts(now)))
                return "new", None
            if r["request_digest"] != request_digest:
                return "conflict", None
            if r["state"] == "done":
                return "replay", r["envelope_id"]
            if (now - parse_ts(r["started_at"])).total_seconds() > IN_PROGRESS_LEASE_SECONDS:
                c.execute("UPDATE idempotency SET started_at=? WHERE tenant_id=? AND idem_key=?",
                          (fmt_ts(now), self.tenant_id, idem_key))
                return "new", None
            return "in_progress", None

    def complete(self, conn, idem_key: str, envelope_id: str) -> None:
        conn.execute("UPDATE idempotency SET state='done', envelope_id=? WHERE tenant_id=? AND idem_key=?",
                     (envelope_id, self.tenant_id, idem_key))

    def release(self, idem_key: str) -> None:
        """Drop an unfinished claim so a retry can run (used when processing failed before commit)."""
        with self.store.tx() as c:
            c.execute("DELETE FROM idempotency WHERE tenant_id=? AND idem_key=? AND state='in_progress'",
                      (self.tenant_id, idem_key))

    def record_protected_action(self, conn, idem_key: str, envelope_id: str, action: str) -> None:
        conn.execute("INSERT INTO protected_actions VALUES (?,?,?,?,?)",
                     (self.tenant_id, idem_key, envelope_id, action, fmt_ts(self.store.clock())))

    def protected_actions(self) -> List[dict]:
        c = self.store.connect()
        try:
            return [dict(r) for r in c.execute("SELECT * FROM protected_actions WHERE tenant_id=? ORDER BY created_at",
                                               (self.tenant_id,))]
        finally:
            c.close()

    # ---- checkpoints ----
    def add_checkpoint(self, body: dict) -> None:
        with self.store.tx() as c:
            r = c.execute("SELECT COALESCE(MAX(id),0)+1 n FROM checkpoints WHERE tenant_id=?",
                          (self.tenant_id,)).fetchone()
            c.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?,?)",
                      (self.tenant_id, r["n"], body["head_seq"], body["head_hash"], canonical_bytes(body).decode(),
                       body["issued_at"]))

    # ---- revocations (live, permanent) ----
    def revoke_license(self, license_id: str, reason: str, actor: str, correlation_id: str) -> None:
        if not isinstance(license_id, str) or not license_id or len(license_id) > 128:
            raise ValueError("BAD_LICENSE_ID")
        with self.store.tx() as c:
            c.execute("INSERT OR IGNORE INTO revocations VALUES (?,?,?,?,?)",
                      (self.tenant_id, license_id, str(reason)[:200], fmt_ts(self.store.clock()), actor))
            self.append([self.new_event("entitlement_denied", actor=actor, correlation_id=correlation_id,
                                        outcome="REVOKED", reason_codes=["LICENSE_REVOKED_BY_ADMIN"],
                                        payload={"license_id": license_id})], c)

    def is_revoked(self, license_id: str) -> bool:
        c = self.store.connect()
        try:
            return c.execute("SELECT 1 FROM revocations WHERE tenant_id=? AND license_id=?",
                             (self.tenant_id, license_id)).fetchone() is not None
        finally:
            c.close()

    # ---- activations ----
    def register_activation(self, license_id: str, instance_id: str, max_activations: int) -> bool:
        """True if this instance is (or becomes) one of at most ``max_activations`` instances of the license."""
        with self.store.tx() as c:
            if c.execute("SELECT 1 FROM activations WHERE tenant_id=? AND license_id=? AND instance_id=?",
                         (self.tenant_id, license_id, instance_id)).fetchone():
                return True
            n = c.execute("SELECT COUNT(*) FROM activations WHERE tenant_id=? AND license_id=?",
                          (self.tenant_id, license_id)).fetchone()[0]
            if n >= max_activations:
                return False
            c.execute("INSERT INTO activations VALUES (?,?,?,?)",
                      (self.tenant_id, license_id, instance_id, fmt_ts(self.store.clock())))
            return True

    # ---- regression cases (human-approved) ----
    def propose_case(self, *, content: bytes, media_type: str, expected_status: str, incident_ref: str,
                     provenance: dict, auth: "AuthContext", correlation_id: str) -> dict:
        from .contracts import AQPD_STATUSES
        if expected_status not in AQPD_STATUSES or not isinstance(content, bytes) or not 0 < len(content) <= 65_536 \
                or not incident_ref or len(incident_ref) > 200:
            raise ValueError("BAD_CASE")
        case_id = "case-" + uuid.uuid4().hex
        digest = sha256_hex(content)
        import base64
        with self.store.tx() as c:
            c.execute("INSERT INTO regression_cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
                      (self.tenant_id, case_id, "proposed", base64.b64encode(content).decode(), media_type or "",
                       digest, expected_status, incident_ref, canonical_bytes(provenance).decode(), auth.label,
                       auth.principal, fmt_ts(self.store.clock())))
            self.append([self.new_event("remediation_created", actor=auth.label, correlation_id=correlation_id,
                                        subject_digest=digest, reason_codes=["REGRESSION_CASE_PROPOSED"],
                                        payload={"case_id": case_id, "incident_ref": incident_ref,
                                                 "expected_status": expected_status})], c)
        return {"case_id": case_id, "status": "proposed", "content_digest": digest}

    def decide_case(self, case_id: str, approve: bool, note: str, auth: "AuthContext", correlation_id: str) -> dict:
        if not auth.allows("admin"):
            raise TenantAccessError("FORBIDDEN")
        with self.store.tx() as c:
            r = c.execute("SELECT * FROM regression_cases WHERE tenant_id=? AND case_id=?",
                          (self.tenant_id, case_id)).fetchone()
            if r is None:
                raise KeyError("CASE_NOT_FOUND")
            if r["status"] != "proposed":
                raise ValueError("CASE_ALREADY_DECIDED")
            if r["proposed_by_principal"] == auth.principal:
                raise TenantAccessError("SELF_APPROVAL_NOT_ALLOWED")
            status = "approved" if approve else "rejected"
            c.execute("UPDATE regression_cases SET status=?, decided_by=?, decided_at=?, decision_note=? "
                      "WHERE tenant_id=? AND case_id=?",
                      (status, auth.label, fmt_ts(self.store.clock()), str(note)[:500], self.tenant_id, case_id))
            if approve:
                self.append([self.new_event("regression_case_added", actor=auth.label, correlation_id=correlation_id,
                                            subject_digest=r["content_digest"], reason_codes=["REGRESSION_CASE_APPROVED"],
                                            payload={"case_id": case_id, "expected_status": r["expected_status"],
                                                     "proposed_by": r["proposed_by"]})], c)
        return {"case_id": case_id, "status": status}

    def cases(self, status: Optional[str] = None) -> List[dict]:
        import base64
        c = self.store.connect()
        try:
            q, a = "SELECT * FROM regression_cases WHERE tenant_id=?", [self.tenant_id]
            if status:
                q += " AND status=?"
                a.append(status)
            out = []
            for r in c.execute(q + " ORDER BY proposed_at, case_id", a):  # nosem: phantom.python.sql-string-building -- q is built only from literal fragments; values are bound via ?
                d = dict(r)
                d["content"] = base64.b64decode(d.pop("content_b64"))
                d["provenance"] = json.loads(d["provenance"])
                out.append(d)
            return out
        finally:
            c.close()
