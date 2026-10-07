"""Audit sidecar: records outbound HTTP calls and DB statements in the tenant ledger.

Write-ahead and fail-closed: an `audit.*.intent` event is appended (and committed) before the
operation is sent; if that append fails the operation is not performed. Completion is recorded as
`audit.*.result` with causation_id pointing at the intent. Payloads hold hashes and metadata only;
header values, query strings and DB parameters are never stored (query/params as digests).
Raw bodies/statements go to the content-addressed evidence store only when `store_bodies=True`.

Scope: in-process interposition (http.client, hence urllib; DB-API connections). It does not see
traffic from code that bypasses these libraries, and a process that can remove the patch can
stop the recording. Ledger tamper-evidence is that of atl.ledger.
"""
import http.client, uuid
from urllib.parse import urlsplit
from .util import sha256, canon



def _digest(b):
    if b is None:
        return None
    if hasattr(b, "read"):
        return "stream"  # unreadable without consuming it; flagged, not hashed
    if isinstance(b, str):
        b = b.encode()
    return sha256(bytes(b)) if isinstance(b, (bytes, bytearray, memoryview)) else "iterable"


class Sidecar:
    def __init__(self, ledger, evidence, tenant, actor="sidecar", store_bodies=False):
        self.ledger, self.evidence, self.tenant, self.actor = ledger, evidence, tenant, actor
        self.store_bodies = store_bodies
        self._orig = None

    # ---- core ----
    def _blob(self, data):
        if not self.store_bodies or data is None or not isinstance(data, (bytes, bytearray, str)):
            return []
        return [self.evidence.put(self.tenant, data)]

    def intent(self, kind, meta, raw=None, correlation_id=None):
        cid = correlation_id or str(uuid.uuid4())
        e = self.ledger.append(self.tenant, f"audit.{kind}.intent", self.actor, meta,
                               evidence=self._blob(raw), correlation_id=cid)
        return cid, e["event_id"]

    def result(self, kind, meta, cid, cause, raw=None):
        try:
            self.ledger.append(self.tenant, f"audit.{kind}.result", self.actor, meta,
                               evidence=self._blob(raw), correlation_id=cid, causation_id=cause)
        except Exception:  # the operation already happened; surface loss of the record loudly
            raise AuditError("result_not_recorded")

    # ---- HTTP (http.client) ----
    def install_http(self):
        if self._orig:
            return
        sc = self
        o_req, o_get = http.client.HTTPConnection.request, http.client.HTTPConnection.getresponse
        self._orig = (o_req, o_get)

        def request(conn, method, url, body=None, headers=None, *a, **kw):
            scheme = "https" if isinstance(conn, http.client.HTTPSConnection) else "http"
            sp = urlsplit(url)
            meta = {"method": method.upper(), "scheme": scheme, "host": conn.host, "port": conn.port,
                    "path": sp.path, "query_sha256": sha256(sp.query) if sp.query else None,
                    "header_names": sorted(k.lower() for k in (headers or {})),
                    "body_sha256": _digest(body)}
            cid, cause = sc.intent("http", meta, body if isinstance(body, (bytes, bytearray, str)) else None)
            conn._atl_audit = (cid, cause)
            return o_req(conn, method, url, body, headers, *a, **kw)

        def getresponse(conn):
            ctx = getattr(conn, "_atl_audit", None)
            try:
                r = o_get(conn)
            except Exception as ex:
                if ctx:
                    sc.result("http", {"error": type(ex).__name__}, *ctx)
                    conn._atl_audit = None
                raise
            if ctx:
                conn._atl_audit = None
                _wrap_response(sc, r, ctx)
            return r

        http.client.HTTPConnection.request = request
        http.client.HTTPConnection.getresponse = getresponse

    def uninstall_http(self):
        if self._orig:
            http.client.HTTPConnection.request, http.client.HTTPConnection.getresponse = self._orig
            self._orig = None

    # ---- DB-API ----
    def wrap_db(self, conn, name="db"):
        return AuditedConnection(conn, self, name)


class AuditError(Exception):
    pass


def _wrap_response(sc, r, ctx):
    """Record the result when the body has been fully read (or closed), with a digest of what was read."""
    import hashlib
    h, buf, done = hashlib.sha256(), [], [False]
    o_read, o_close = r.read, r.close

    def finish():
        if done[0]:
            return
        done[0] = True
        data = b"".join(buf) if sc.store_bodies else None
        sc.result("http", {"status": r.status, "response_sha256": h.hexdigest(),
                           "complete": r.isclosed() or r.length in (0, None)}, *ctx, raw=data)

    def read(amt=None):
        d = o_read(amt)
        h.update(d)
        if sc.store_bodies:
            buf.append(d)
        if not d or r.isclosed():
            finish()
        return d

    def close():
        o_close()
        finish()

    r.read, r.close = read, close


class AuditedCursor:
    def __init__(self, cur, sc, name):
        self._c, self._sc, self._n = cur, sc, name

    def _run(self, op, sql, params, many=False):
        meta = {"db": self._n, "op": op, "statement_sha256": sha256(sql),
                "params_sha256": sha256(canon(_jsonable(params))) if params is not None else None,
                "executemany": many}
        cid, cause = self._sc.intent("db", meta, sql)
        try:
            out = (self._c.executemany if many else self._c.execute)(sql, params) if params is not None \
                else self._c.execute(sql)
        except Exception as ex:
            self._sc.result("db", {"error": type(ex).__name__}, cid, cause)
            raise
        self._sc.result("db", {"rowcount": self._c.rowcount}, cid, cause)
        return self if out is self._c else out

    def execute(self, sql, params=None):
        return self._run("execute", sql, params)

    def executemany(self, sql, params):
        return self._run("executemany", sql, params, many=True)

    def __iter__(self):
        return iter(self._c)

    def __getattr__(self, k):
        return getattr(self._c, k)


class AuditedConnection:
    def __init__(self, conn, sc, name):
        self._conn, self._sc, self._n = conn, sc, name

    def cursor(self, *a, **kw):
        return AuditedCursor(self._conn.cursor(*a, **kw), self._sc, self._n)

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, params):
        return self.cursor().executemany(sql, params)

    def _tx(self, op):
        cid, cause = self._sc.intent("db", {"db": self._n, "op": op})
        try:
            getattr(self._conn, op)()
        except Exception as ex:
            self._sc.result("db", {"error": type(ex).__name__}, cid, cause)
            raise
        self._sc.result("db", {"ok": True}, cid, cause)

    def commit(self):
        self._tx("commit")

    def rollback(self):
        self._tx("rollback")

    def __enter__(self):
        return self

    def __exit__(self, t, v, tb):
        self.rollback() if t else self.commit()
        return False

    def __getattr__(self, k):
        return getattr(self._conn, k)


def _jsonable(p):
    if isinstance(p, dict):
        return {str(k): _jsonable(v) for k, v in p.items()}
    if isinstance(p, (list, tuple)):
        return [_jsonable(v) for v in p]
    if isinstance(p, (bytes, bytearray)):
        return {"b64sha256": sha256(bytes(p))}
    if p is None or isinstance(p, (bool, int, float, str)):
        return p
    return str(p)
