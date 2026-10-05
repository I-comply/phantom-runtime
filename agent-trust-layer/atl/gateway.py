import json, os, secrets, sqlite3, urllib.request, uuid
from pathlib import Path
from .util import canon, sha256, mac, eq, now_ms, valid_id, http_open
from .store import DB
from .keys import make_provider
from .ledger import Ledger, anchor_key, verify_conn
from .evidence import Evidence
from .identity import Identity, AuthError
from .policy import Policy
from .executor import make_executor
from .client import req_string, intent_digest, approval_string

MAX_PARAMS = 65536
PRE_AUTH_FAILS = 30        # per (source, tenant, agent)
PRE_AUTH_FAILS_SRC = 1000  # per source backstop against identity spraying


class BadRequest(Exception):
    pass


class RateLimited(Exception):
    pass


class Core:
    def __init__(self, data_dir, manifest=None):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        self.keys = make_provider(self.dir)
        self.db = DB(self.dir / "atl.db")
        self.ident = Identity(self.db, self.keys)
        self.ledger = Ledger(self.db, self.keys)
        self.evidence = Evidence(self.dir / "evidence")
        mp = Path(manifest) if manifest else self.dir / "capabilities.json"
        self.policy = Policy.load(mp)  # raises -> refuse to start (fail closed)
        self.executor = make_executor(self.dir / "sandbox")
        self.anchor_file = self.dir / "anchors.jsonl"

    # ---- counters ----
    def _hit(self, k):
        c, b = self.db.conn(), now_ms() // 60000
        c.execute("INSERT INTO rate VALUES(?,?,1) ON CONFLICT(k,bucket) DO UPDATE SET n=n+1", (k, b))
        c.execute("DELETE FROM rate WHERE bucket<?", (b - 5,))
        return c.execute("SELECT n FROM rate WHERE k=? AND bucket=?", (k, b)).fetchone()["n"]

    def _count(self, k):
        r = self.db.conn().execute("SELECT n FROM rate WHERE k=? AND bucket=?", (k, now_ms() // 60000)).fetchone()
        return r["n"] if r else 0

    # ---- admin ----
    def admin_principal(self, op, tenant, pid, kind="agent", ttl_days=None):
        if op == "issue":
            out = self.ident.issue(tenant, pid, kind, ttl_days)
        elif op == "rotate":
            out = self.ident.rotate(tenant, pid, kind, ttl_days)
        elif op == "revoke":
            self.ident.revoke(tenant, pid, kind)
            out = {"tenant_id": tenant, "principal_id": pid, "kind": kind, "revoked": True}
        else:
            raise ValueError("bad_op")
        self.ledger.append(tenant, f"identity.{op}", "admin",
                           {"principal_id": pid, "kind": kind, "key_version": out.get("key_version"),
                            "expires_at": out.get("expires_at")})
        return out

    def rotate_master(self):
        """New master version; each tenant ledger records it in a key.rotated event. Old versions stay readable."""
        v = self.keys.rotate()
        tenants = [r["tenant_id"] for r in self.db.conn().execute("SELECT tenant_id FROM tenants")]
        for t in tenants:
            self.ledger.rotate_tenant(t)
        return {"master_version": v, "tenants": tenants}

    def anchor(self, tenant):
        r = self.ledger.verify(tenant)
        if not r["ok"] or r["count"] == 0:
            raise ValueError("nothing_to_anchor_or_ledger_invalid")
        mv = self.keys.current_version()
        a = {"tenant": tenant, "seq": r["count"], "hash": r["head"], "ts": now_ms(), "mv": mv}
        a["mac"] = mac(anchor_key(self.keys.get(mv), tenant), f"{tenant}|{a['seq']}|{a['hash']}|{a['ts']}")
        with open(self.anchor_file, "a") as f:
            f.write(json.dumps(a, sort_keys=True) + "\n")
        url = os.environ.get("ATL_ANCHOR_WEBHOOK")
        if url:
            try:
                http_open(urllib.request.Request(
                    url, json.dumps(a).encode(), {"Content-Type": "application/json"}), timeout=5).read()
                a["webhook"] = "sent"
            except Exception as e:
                a["webhook"] = f"failed:{type(e).__name__}"
        return a

    def anchors(self):
        if not self.anchor_file.exists():
            return []
        return [json.loads(l) for l in self.anchor_file.read_text().splitlines() if l.strip()]

    def verify_all(self, tenant):
        r = verify_conn(self.db.conn(), tenant, self.keys, self.anchors())
        if r["ok"]:
            for e in self.ledger.events(tenant, limit=10 ** 9):
                for h in e["evidence"]:
                    if not self.evidence.check(tenant, h):
                        return {"ok": False, "count": r["count"], "error": f"evidence missing/corrupt {h[:12]} at seq {e['seq']}"}
        return r

    # ---- invoke ----
    def invoke(self, req, src="local"):
        try:
            return self._invoke(req, src)
        except AuthError:
            return {"ok": False, "status": 401, "error": "unauthorized"}
        except RateLimited:
            return {"ok": False, "status": 429, "error": "rate_limited"}
        except BadRequest as e:
            return {"ok": False, "status": 400, "error": str(e)}
        except Exception as e:
            return {"ok": False, "status": 500, "error": "internal"}

    def _fail(self, src, t, a):
        self._hit(f"fail:{src}:{t}:{a}")
        self._hit(f"fail:{src}")
        raise AuthError()

    def _invoke(self, req, src):
        if not isinstance(req, dict):
            raise BadRequest("bad_request")
        for k in ("tenant_id", "agent_id", "action", "timestamp", "nonce", "signature", "key_version"):
            if k not in req:
                raise BadRequest(f"missing:{k}")
        t, a, action, nonce, sig = (req[k] for k in ("tenant_id", "agent_id", "action", "nonce", "signature"))
        ts, ver = req["timestamp"], req["key_version"]
        if not (valid_id(t) and valid_id(a) and valid_id(action) and isinstance(nonce, str) and 8 <= len(nonce) <= 64
                and isinstance(sig, str) and len(sig) <= 128 and type(ts) is int and type(ver) is int):
            raise BadRequest("malformed")
        if self._count(f"fail:{src}:{t}:{a}") >= PRE_AUTH_FAILS or self._count(f"fail:{src}") >= PRE_AUTH_FAILS_SRC:
            raise RateLimited()
        params = req.get("params", {})
        if not isinstance(params, dict):
            raise BadRequest("params_not_object")
        try:
            pc = canon(params)
        except ValueError as e:
            raise BadRequest(f"params:{e}")
        if len(pc) > MAX_PARAMS:
            raise BadRequest("params_too_large")
        idem = req.get("idempotency_key")
        if idem is not None and not valid_id(idem):
            raise BadRequest("bad_idempotency_key")

        n = now_ms()
        row = self.ident.lookup(t, a, "agent")
        good = eq(mac(self.ident.derive_row(row, t, a, "agent", ver), req_string(t, a, ver, action, params, ts, nonce)), sig)
        if not good or row is None or row["key_version"] != ver:
            self._fail(src, t, a)
        if abs(n - ts) > self.policy.limits["skew_s"] * 1000:
            self._fail(src, t, a)
        c = self.db.conn()
        c.execute("DELETE FROM nonces WHERE expires<?", (n,))
        if not self.ident.usable(row, ver, n):
            if self._hit(f"rej:{t}:{a}") <= 30:
                self.ledger.append(t, "identity.rejected", a, {"reason": "revoked_or_expired", "key_version": ver})
            raise AuthError()
        try:
            c.execute("INSERT INTO nonces VALUES(?,?,?)", (t, nonce, n + 2 * self.policy.limits["skew_s"] * 1000))
        except sqlite3.IntegrityError:
            if self._hit(f"rej:{t}:{a}") <= 30:
                self.ledger.append(t, "identity.rejected", a, {"reason": "replay"})
            raise AuthError()
        if self._hit(f"p:{t}:{a}") > self.policy.limits["per_minute"]:
            raise RateLimited()

        digest = intent_digest(t, a, action, params)
        if idem:
            try:
                c.execute("INSERT INTO requests VALUES(?,?,?,NULL)", (t, idem, digest))
            except sqlite3.IntegrityError:
                r = c.execute("SELECT digest,response FROM requests WHERE tenant_id=? AND idem_key=?", (t, idem)).fetchone()
                if r["digest"] != digest:
                    raise BadRequest("idempotency_key_reuse")
                if r["response"] is None:
                    return {"ok": False, "status": 409, "error": "in_progress"}
                return dict(json.loads(r["response"]), replayed=True)
        resp = self._decide_and_run(t, a, action, params, digest, idem, req.get("approval"), n)
        if idem:
            c.execute("UPDATE requests SET response=? WHERE tenant_id=? AND idem_key=?", (canon(resp), t, idem))
        return resp

    def _check_approval(self, t, a, digest, ap, n):
        if not isinstance(ap, dict):
            return None, "approval_malformed"
        try:
            aid, av, exp, sig = ap["approver_id"], ap["key_version"], ap["expires_at"], ap["signature"]
        except KeyError:
            return None, "approval_malformed"
        if not (valid_id(aid) and type(av) is int and type(exp) is int and isinstance(sig, str)):
            return None, "approval_malformed"
        if aid == a:
            return None, "self_approval"
        row = self.ident.lookup(t, aid, "approver")
        good = eq(mac(self.ident.derive_row(row, t, aid, "approver", av), approval_string(t, aid, av, digest, exp)), sig)
        if not good or not self.ident.usable(row, av, n):
            return None, "approval_invalid"
        if exp <= n or exp > n + self.policy.limits["approval_ttl_s"] * 1000:
            return None, "approval_expired_or_too_long"
        try:
            self.db.conn().execute("INSERT INTO approvals_used VALUES(?,?)", (sha256(digest + aid + str(exp) + sig), n))
        except sqlite3.IntegrityError:
            return None, "approval_already_used"
        return aid, None

    def _decide_and_run(self, t, a, action, params, digest, idem, approval, n):
        corr = str(uuid.uuid4())
        try:
            d = self.policy.decide(a, action, params)
        except Exception:
            d = {"decision": "deny", "reason": "policy_error", "risk": None}
        approved_by = None
        if d["decision"] == "needs_approval" and approval is not None:
            approved_by, err = self._check_approval(t, a, digest, approval, n)
            if approved_by:
                d = dict(d, decision="allow", reason="approved")
            else:
                d = dict(d, decision="deny", reason=err)
        ph = self.evidence.put(t, canon(params))
        dec = self.ledger.append(t, "authz.decision", a, {
            "action": action, "decision": d["decision"], "reason": d["reason"], "risk": d["risk"],
            "intent_digest": digest, "approved_by": approved_by, "params_hash": ph},
            [ph], corr, None, idem)
        base = {"decision": d["decision"], "reason": d["reason"], "correlation_id": corr, "intent_digest": digest}
        if d["decision"] != "allow":
            return dict(base, ok=False, status=403)
        inv = self.ledger.append(t, "tool.invoked", a, {"action": action, "params_hash": ph}, [ph], corr, dec["event_id"])
        out = self.executor.run(action, params, self.policy.limits["timeout_s"], t)
        if out["ok"]:
            oh = self.evidence.put(t, canon(out["output"]))
            self.ledger.append(t, "tool.completed", a, {"action": action, "output_hash": oh,
                               "duration_ms": out["duration_ms"]}, [oh], corr, inv["event_id"])
            return dict(base, ok=True, status=200, result=out["output"], output_hash=oh)
        self.ledger.append(t, "tool.failed", a, {"action": action, "error": out["error"],
                           "duration_ms": out["duration_ms"]}, [], corr, inv["event_id"])
        return dict(base, ok=False, status=502, error=out["error"])
