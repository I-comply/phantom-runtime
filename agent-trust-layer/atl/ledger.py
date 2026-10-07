import hmac, hashlib, json, sqlite3, uuid
from .util import canon, sha256, mac, eq, now_ms

GENESIS = "0" * 64


def ledger_key(master, tenant):
    return hmac.new(master, b"ledger|" + tenant.encode(), hashlib.sha256).digest()


def anchor_key(master, tenant):
    return hmac.new(master, b"anchor|" + tenant.encode(), hashlib.sha256).digest()


def _body(r):
    return {
        "tenant_id": r["tenant_id"], "seq": r["seq"], "event_id": r["event_id"], "ts": r["ts"],
        "type": r["type"], "actor": r["actor"], "correlation_id": r["correlation_id"],
        "causation_id": r["causation_id"], "idempotency_key": r["idempotency_key"],
        "payload": json.loads(r["payload"]), "evidence": json.loads(r["evidence"]),
        "prev_hash": r["prev_hash"],
    }


class StaticKeys:
    """Single-version keyring (offline verification with a raw master key)."""
    def __init__(self, master):
        self.master = master

    def get(self, version):
        if version != 1:
            raise KeyError(version)
        return self.master


def tenant_master_version(conn, tenant):
    r = conn.execute("SELECT payload FROM events WHERE tenant_id=? AND type='key.rotated' ORDER BY seq DESC LIMIT 1",
                     (tenant,)).fetchone()
    return json.loads(r["payload"])["master_version"] if r else 1


class Ledger:
    def __init__(self, db, keys):
        self.db, self.keys = db, keys

    def append(self, tenant, type, actor, payload, evidence=(), correlation_id=None,
               causation_id=None, idempotency_key=None):
        c = self.db.conn()
        pl = canon(payload)
        ev = list(evidence)
        c.execute("BEGIN IMMEDIATE")
        try:
            last = c.execute("SELECT seq,hash FROM events WHERE tenant_id=? ORDER BY seq DESC LIMIT 1",
                             (tenant,)).fetchone()
            ver, cur = tenant_master_version(c, tenant), self.keys.current_version()
            if type != "key.rotated" and ver < cur:  # catch up: new tenant or missed rotation
                last = self._write(c, tenant, last, ver, "key.rotated", "system",
                                   {"master_version": cur, "previous": ver}, [], None, None, None)
                ver = cur
            e = self._write(c, tenant, last, ver, type, actor, json.loads(pl), ev,
                            correlation_id, causation_id, idempotency_key)
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        return e

    def _write(self, c, tenant, last, ver, type, actor, payload, ev, correlation_id, causation_id, idem):
        seq = last["seq"] + 1 if last else 1
        e = {"tenant_id": tenant, "seq": seq, "event_id": str(uuid.uuid4()), "ts": now_ms(),
             "type": type, "actor": actor, "correlation_id": correlation_id,
             "causation_id": causation_id, "idempotency_key": idem,
             "payload": payload, "evidence": ev,
             "prev_hash": last["hash"] if last else GENESIS}
        h = sha256(canon(e))
        m = mac(ledger_key(self.keys.get(ver), tenant), h)  # signed under the version in force BEFORE this event
        c.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (tenant, seq, e["event_id"], e["ts"], type, actor, correlation_id, causation_id,
                   idem, canon(payload), canon(ev), e["prev_hash"], h, m))
        e["hash"], e["mac"] = h, m
        return e

    def rotate_tenant(self, tenant):
        """Record the current master version in the tenant ledger (no-op if already current)."""
        c = self.db.conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            ver, cur = tenant_master_version(c, tenant), self.keys.current_version()
            e = None
            if ver < cur:
                last = c.execute("SELECT seq,hash FROM events WHERE tenant_id=? ORDER BY seq DESC LIMIT 1",
                                 (tenant,)).fetchone()
                e = self._write(c, tenant, last, ver, "key.rotated", "admin",
                                {"master_version": cur, "previous": ver}, [], None, None, None)
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        return e

    def events(self, tenant, limit=100, after=0):
        rows = self.db.conn().execute(
            "SELECT * FROM events WHERE tenant_id=? AND seq>? ORDER BY seq LIMIT ?",
            (tenant, after, int(limit))).fetchall()
        return [dict(_body(r), hash=r["hash"], mac=r["mac"]) for r in rows]

    def iter_events(self, tenant, chunk=1000):
        """Stream a tenant's events in seq order without loading the whole ledger."""
        after = 0
        while True:
            rows = self.events(tenant, chunk, after)
            if not rows:
                return
            yield from rows
            after = rows[-1]["seq"]

    def verify(self, tenant, anchors=()):
        return verify_conn(self.db.conn(), tenant, self.keys, anchors)


def verify_conn(conn, tenant, master=None, anchors=()):
    prev, n, hashes, ver = GENESIS, 0, {}, 1
    keys = StaticKeys(master) if isinstance(master, (bytes, bytearray)) else master
    for r in conn.execute("SELECT * FROM events WHERE tenant_id=? ORDER BY seq", (tenant,)):
        n += 1
        if r["seq"] != n:
            return {"ok": False, "count": n - 1, "error": f"sequence gap at {n}"}
        if r["prev_hash"] != prev:
            return {"ok": False, "count": n - 1, "error": f"broken link at seq {n}"}
        h = sha256(canon(_body(r)))
        if h != r["hash"]:
            return {"ok": False, "count": n - 1, "error": f"content hash mismatch at seq {n}"}
        if keys:
            try:
                key = ledger_key(keys.get(ver), tenant)
            except Exception:
                return {"ok": False, "count": n - 1, "error": f"master key version {ver} unavailable at seq {n}"}
            if not eq(mac(key, h), r["mac"]):
                return {"ok": False, "count": n - 1, "error": f"mac mismatch at seq {n}"}
        if r["type"] == "key.rotated":
            nv = json.loads(r["payload"]).get("master_version")
            if type(nv) is not int or nv <= ver:
                return {"ok": False, "count": n - 1, "error": f"bad key.rotated at seq {n}"}
            ver = nv
        hashes[n] = prev = h
    for a in anchors:
        if a.get("tenant") != tenant:
            continue
        if keys:
            try:
                ak = anchor_key(keys.get(a.get("mv", 1)), tenant)
            except Exception:
                return {"ok": False, "count": n, "error": f"anchor key unavailable at seq {a['seq']}"}
            if not eq(mac(ak, f"{a['tenant']}|{a['seq']}|{a['hash']}|{a['ts']}"), a.get("mac", "")):
                return {"ok": False, "count": n, "error": f"anchor mac invalid at seq {a['seq']}"}
        if a["seq"] > n:
            return {"ok": False, "count": n, "error": f"ledger truncated below anchor seq {a['seq']}"}
        if hashes.get(a["seq"]) != a["hash"]:
            return {"ok": False, "count": n, "error": f"ledger diverges from anchor at seq {a['seq']}"}
    return {"ok": True, "count": n, "head": prev, "error": None}
