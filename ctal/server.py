"""Minimal authenticated HTTP API (stdlib). Tenant comes from the API key, never from the request body.

POST /v1/gate            role gate    -> signed envelope (Idempotency-Key header required)
GET  /v1/envelopes/<id>  role read
GET  /v1/events?...      role read    filters: from,to,outcome,policy_version,reason_code,subject_digest,correlation_id,event_type,limit,offset
GET  /v1/export          role export  -> signed evidence zip
POST /v1/policies        role admin   -> publish new immutable policy version
GET  /v1/metrics         role admin   -> process-local request/decision counters
GET  /v1/metrics/summary role read    -> ledger-derived decision/latency/regression metrics (?from=&to=)
GET  /v1/release         role read    -> running release digest
GET  /v1/licenses/expiring role read  -> licenses seen whose valid_until is within ?days=30
POST /v1/revocations     role admin   -> permanently revoke a license id for this tenant
POST /v1/incidents       role propose -> propose a regression case from a reviewed incident
GET  /v1/regressions     role read    -> cases (digests only; ?status=)
POST /v1/regressions/<id>/approve|reject  role admin, must be a different API key than the proposer
POST /v1/regressions/replay  role read -> run approved cases against a policy version (AQPD only, no side effects)
Optional: TLS (tls=(cert,key), TLS>=1.2), per-key rate limiting (429 + Retry-After), W3C traceparent -> correlation id.
GET  /healthz, /readyz   unauthenticated, no data
"""
from __future__ import annotations

import base64
import json
import logging
import re
import ssl
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .canon import CanonError, parse_strict
from .export import build_export
from . import metrics as metrics_mod
from .gate import Gate, GateError
from .keys import Signer, TrustStore
from .store import TenantAccessError

MAX_BODY = 1_048_576
log = logging.getLogger("ctal")


_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


class _Bucket:
    """Token bucket per key. capacity tokens, refilled at ``per_sec``."""
    def __init__(self, capacity: int, per_sec: float):
        self.cap, self.rate, self.lock, self.b = capacity, per_sec, threading.Lock(), {}

    def take(self, key: str) -> float:
        """0.0 if allowed, else seconds to wait."""
        now = time.monotonic()
        with self.lock:
            if len(self.b) > 10_000:
                self.b.clear()
            tokens, last = self.b.get(key, (float(self.cap), now))
            tokens = min(self.cap, tokens + (now - last) * self.rate)
            if tokens < 1:
                self.b[key] = (tokens, now)
                return (1 - tokens) / self.rate
            self.b[key] = (tokens - 1, now)
            return 0.0


def make_server(host: str, port: int, gate: Gate, export_signer: Signer, public_trust: TrustStore,
                max_concurrent: int = 32, rate_limit=None, tls=None) -> ThreadingHTTPServer:
    """rate_limit=(capacity, refill_per_second) or None; tls=(cert_path, key_path) or None."""
    store = gate.store
    sem = threading.BoundedSemaphore(max_concurrent)
    metrics = {"requests": 0, "decisions": {}, "rate_limited": 0}
    bucket = _Bucket(*rate_limit) if rate_limit else None

    class H(BaseHTTPRequestHandler):
        server_version = "ctal"
        timeout = 15

        def log_message(self, *a):  # structured logs below; never log bodies or tokens
            pass

        def _send(self, code, obj=None, raw=None, ctype="application/json"):
            body = raw if raw is not None else json.dumps(obj if obj is not None else {}).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            log.info(json.dumps({"ts": time.time(), "method": self.command, "path": urlparse(self.path).path,
                                 "status": code, "req": self._rid, "trace": self._trace}))

        def _auth(self):
            h = self.headers.get("Authorization", "")
            return store.authenticate(h[7:] if h.startswith("Bearer ") else None)

        def _dispatch(self):
            self._rid = uuid.uuid4().hex[:12]
            m = _TRACEPARENT.match(self.headers.get("traceparent", ""))
            self._trace = m.group(1) if m and m.group(1) != "0" * 32 else None
            u = urlparse(self.path)
            if u.path == "/healthz":
                return self._send(200, {"status": "ok"})
            if u.path == "/readyz":
                ok = store.schema_version() is not None
                return self._send(200 if ok else 503, {"ready": ok})
            if not sem.acquire(blocking=False):
                return self._send(503, {"error": "OVERLOADED"})
            try:
                metrics["requests"] += 1
                auth = self._auth()
                if bucket is not None:
                    wait = bucket.take(auth.principal if auth else "ip:" + self.client_address[0])
                    if wait:
                        metrics["rate_limited"] += 1
                        self.send_response(429)
                        self.send_header("Retry-After", str(int(wait) + 1))
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                if auth is None:
                    return self._send(401, {"error": "UNAUTHENTICATED"})
                try:
                    self._route(u, auth)
                except GateError as e:
                    self._send(e.http, {"error": e.code})
                except TenantAccessError as e:
                    self._send(403, {"error": str(e)})
                except KeyError as e:
                    self._send(404, {"error": str(e).strip("'\"")})
                except Exception:
                    log.exception("unhandled")
                    self._send(500, {"error": "INTERNAL_ERROR", "outcome": "ERROR"})
            finally:
                sem.release()

        do_GET = do_POST = _dispatch

        @staticmethod
        def _need(auth, perm):
            if not auth.allows(perm):
                raise GateError("FORBIDDEN", 403)

        def _body(self):
            n = int(self.headers.get("Content-Length", "0") or 0)
            if n > MAX_BODY or n < 0:
                raise GateError("BODY_TOO_LARGE", 413)
            try:
                return parse_strict(self.rfile.read(n))
            except CanonError as e:
                raise GateError("MALFORMED_REQUEST:" + e.code, 400)

        def _route(self, u, auth):
            led = store.for_tenant(auth)
            if self.command == "POST" and u.path == "/v1/gate":
                if not auth.allows("gate"):
                    raise GateError("FORBIDDEN", 403)
                b = self._body()
                try:
                    content = base64.b64decode(b["content_b64"], validate=True)
                    tok = b.get("entitlement_token")
                    res = gate.process(
                        auth, content=content, media_type=b.get("media_type", ""),
                        entitlement_token=tok.encode() if isinstance(tok, str) else None,
                        product_id=b["product_id"], policy_id=b["policy_id"],
                        idempotency_key=self.headers.get("Idempotency-Key", ""),
                        correlation_id=str(b.get("correlation_id") or self._trace or self._rid), claimed_tenant=b.get("tenant_id"),
                        instance_id=b.get("instance_id"))
                except (KeyError, TypeError, ValueError):
                    raise GateError("BAD_REQUEST", 400)
                o = res["envelope"]["decision"]["outcome"]
                metrics["decisions"][o] = metrics["decisions"].get(o, 0) + 1
                return self._send(200 if res["replayed"] else 201, res)
            if self.command == "POST" and u.path == "/v1/policies":
                if not auth.allows("admin"):
                    raise GateError("FORBIDDEN", 403)
                b = self._body()
                try:
                    return self._send(201, led.publish_policy(b["policy_id"], b["body"], auth.label, self._rid))
                except (KeyError, ValueError):
                    raise GateError("BAD_REQUEST", 400)
            if self.command == "GET" and u.path == "/v1/metrics":
                if not auth.allows("admin"):
                    raise GateError("FORBIDDEN", 403)
                return self._send(200, metrics)
            if self.command == "GET" and u.path == "/v1/metrics/summary":
                self._need(auth, "read")
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                return self._send(200, metrics_mod.summary(led.all_events(), q.get("from"), q.get("to")))
            if self.command == "GET" and u.path == "/v1/release":
                self._need(auth, "read")
                return self._send(200, {"software_release_digest": gate.release_digest})
            if self.command == "GET" and u.path == "/v1/licenses/expiring":
                self._need(auth, "read")
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                try:
                    days = int(q.get("days", 30))
                except ValueError:
                    raise GateError("BAD_QUERY", 400)
                return self._send(200, {"licenses": metrics_mod.expiring_licenses(led.all_events(), days, gate.clock())})
            if self.command == "POST" and u.path == "/v1/revocations":
                self._need(auth, "admin")
                b = self._body()
                try:
                    led.revoke_license(b["license_id"], b.get("reason", ""), auth.label, self._trace or self._rid)
                except (KeyError, ValueError, TypeError):
                    raise GateError("BAD_REQUEST", 400)
                return self._send(201, {"revoked": b["license_id"]})
            if self.command == "POST" and u.path == "/v1/incidents":
                self._need(auth, "propose")
                b = self._body()
                try:
                    r = led.propose_case(content=base64.b64decode(b["content_b64"], validate=True), media_type=b.get("media_type", ""),
                                         expected_status=b["expected_status"], incident_ref=b["incident_ref"],
                                         provenance=b.get("provenance") or {}, auth=auth, correlation_id=self._trace or self._rid)
                except (KeyError, ValueError, TypeError):
                    raise GateError("BAD_REQUEST", 400)
                return self._send(201, r)
            if self.command == "GET" and u.path == "/v1/regressions":
                self._need(auth, "read")
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                return self._send(200, {"cases": [{k: v for k, v in c.items() if k != "content"} for c in led.cases(q.get("status"))]})
            m = re.match(r"^/v1/regressions/(case-[0-9a-f]{32})/(approve|reject)$", u.path)
            if self.command == "POST" and m:
                self._need(auth, "admin")
                b = self._body() if int(self.headers.get("Content-Length", "0") or 0) else {}
                try:
                    return self._send(200, led.decide_case(m.group(1), m.group(2) == "approve", b.get("note", ""), auth, self._trace or self._rid))
                except ValueError as e:
                    raise GateError(str(e), 409)
            if self.command == "POST" and u.path == "/v1/regressions/replay":
                self._need(auth, "read")
                b = self._body()
                pid, ver = b.get("policy_id"), b.get("version")
                if not isinstance(pid, str) or (ver is not None and not isinstance(ver, int)):
                    raise GateError("BAD_REQUEST", 400)
                results = []
                for c in led.cases("approved"):
                    pol, r = gate.assess_only(led, c["content"], c["media_type"], pid, ver)
                    results.append({"case_id": c["case_id"], "expected": c["expected_status"], "actual": r.status,
                                    "reason_codes": r.reason_codes, "passed": r.status == c["expected_status"]})
                pol = led.get_policy(pid, ver)
                if pol is None:
                    raise GateError("POLICY_NOT_FOUND", 422)
                return self._send(200, {"policy_id": pid, "policy_version": pol["version"], "policy_digest": pol["digest"],
                                        "total": len(results), "passed": sum(1 for r in results if r["passed"]),
                                        "failed": [r for r in results if not r["passed"]], "results": results})
            if self.command == "GET" and u.path.startswith("/v1/envelopes/"):
                if not auth.allows("read"):
                    raise GateError("FORBIDDEN", 403)
                env = led.get_envelope(u.path.rsplit("/", 1)[1])
                return self._send(200, env) if env else self._send(404, {"error": "NOT_FOUND"})
            if self.command == "GET" and u.path == "/v1/events":
                if not auth.allows("read"):
                    raise GateError("FORBIDDEN", 403)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                try:
                    evs = led.events(
                        from_time=q.get("from"), to_time=q.get("to"), outcome=q.get("outcome"),
                        policy_version=int(q["policy_version"]) if "policy_version" in q else None,
                        reason_code=q.get("reason_code"), subject_digest=q.get("subject_digest"),
                        correlation_id=q.get("correlation_id"), event_type=q.get("event_type"),
                        limit=int(q.get("limit", 100)), offset=int(q.get("offset", 0)))
                except ValueError:
                    raise GateError("BAD_QUERY", 400)
                return self._send(200, {"events": evs})
            if self.command == "GET" and u.path == "/v1/export":
                if not auth.allows("export"):
                    raise GateError("FORBIDDEN", 403)
                z = build_export(led, export_signer, public_trust, actor=auth.label, correlation_id=self._rid)
                return self._send(200, raw=z, ctype="application/zip")
            self._send(404, {"error": "NOT_FOUND"})

    srv = ThreadingHTTPServer((host, port), H)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(tls[0], tls[1])
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv
