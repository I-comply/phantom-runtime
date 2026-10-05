import hmac, hashlib
from .util import now_ms, valid_id


class AuthError(Exception):
    pass


class Identity:
    def __init__(self, db, keys):
        self.db, self.keys = db, keys

    def derive(self, tenant, pid, kind, ver, mver=None):
        """mver = master key version the principal was issued under (default: current)."""
        master = self.keys.get(mver if mver is not None else self.keys.current_version())
        return hmac.new(master, f"principal|{tenant}|{kind}|{pid}|{ver}".encode(), hashlib.sha256).digest()

    def derive_row(self, row, tenant, pid, kind, ver):
        return self.derive(tenant, pid, kind, ver, row["master_version"] if row is not None else 1)

    def lookup(self, tenant, pid, kind):
        return self.db.conn().execute(
            "SELECT * FROM principals WHERE tenant_id=? AND principal_id=? AND kind=?",
            (tenant, pid, kind)).fetchone()

    def create_tenant(self, tenant):
        if not valid_id(tenant):
            raise ValueError("bad_tenant_id")
        self.db.conn().execute("INSERT OR IGNORE INTO tenants VALUES(?,?)", (tenant, now_ms()))

    def _out(self, tenant, pid, kind, ver, exp, mver):
        return {"tenant_id": tenant, "principal_id": pid, "kind": kind, "key_version": ver,
                "secret": self.derive(tenant, pid, kind, ver, mver).hex(), "expires_at": exp}

    def issue(self, tenant, pid, kind="agent", ttl_days=None):
        if not (valid_id(tenant) and valid_id(pid)) or kind not in ("agent", "approver"):
            raise ValueError("bad_id")
        self.create_tenant(tenant)
        if self.lookup(tenant, pid, kind):
            raise ValueError("principal_exists")
        n = now_ms()
        exp = n + int(ttl_days * 86400000) if ttl_days else None
        mv = self.keys.current_version()
        self.db.conn().execute("INSERT INTO principals VALUES(?,?,?,?,?,?,?,NULL,?)",
                               (tenant, pid, kind, 1, "active", n, exp, mv))
        return self._out(tenant, pid, kind, 1, exp, mv)

    def rotate(self, tenant, pid, kind="agent", ttl_days=None):
        row = self.lookup(tenant, pid, kind)
        if not row:
            raise ValueError("unknown_principal")
        ver, n = row["key_version"] + 1, now_ms()
        exp = n + int(ttl_days * 86400000) if ttl_days else None
        mv = self.keys.current_version()
        self.db.conn().execute(
            "UPDATE principals SET key_version=?,status='active',not_before=?,expires_at=?,revoked_at=NULL,"
            "master_version=? WHERE tenant_id=? AND principal_id=? AND kind=?", (ver, n, exp, mv, tenant, pid, kind))
        return self._out(tenant, pid, kind, ver, exp, mv)

    def revoke(self, tenant, pid, kind="agent"):
        if not self.lookup(tenant, pid, kind):
            raise ValueError("unknown_principal")
        self.db.conn().execute(
            "UPDATE principals SET status='revoked',revoked_at=? WHERE tenant_id=? AND principal_id=? AND kind=?",
            (now_ms(), tenant, pid, kind))

    @staticmethod
    def usable(row, ver, n):
        return (row is not None and row["status"] == "active" and row["key_version"] == ver
                and row["not_before"] <= n and (row["expires_at"] is None or n < row["expires_at"]))
