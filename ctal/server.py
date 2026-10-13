"""Minimal authenticated HTTP API (stdlib). Tenant comes from the API key, never from the request body.

POST /v1/gate            role gate    -> signed envelope (Idempotency-Key header required)
GET  /v1/envelopes/<id>  role read
GET  /v1/events?...      role read    filters: from,to,outcome,policy_version,reason_code,subject_digest,correlation_id,event_type,limit,offset
GET  /v1/export          role export  -> signed evidence zip
POST /v1/policies        role admin   -> publish new immutable policy version
GET  /v1/metrics         role admin   -> process-local request/decision counters
GET  /healthz, /readyz   unauthenticated, no data
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .canon import CanonError, parse_strict
from .export import build_export
from .gate import Gate, GateError
from .keys import Signer, TrustStore

MAX_BODY = 1_048_576
log = logging.getLogger("ctal")


def make_server(host: str, port: int, gate: Gate, export_signer: Signer, public_trust: TrustStore,
                max_concurrent: int = 32) -> ThreadingHTTPServer:
    store = gate.store
    sem = threading.BoundedSemaphore(max_concurrent)
    metrics = {"requests": 0, "decisions": {}}

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
                                 "status": code, "req": self._rid}))

        def _auth(self):
            h = self.headers.get("Authorization", "")
            return store.authenticate(h[7:] if h.startswith("Bearer ") else None)

        def _dispatch(self):
            self._rid = uuid.uuid4().hex[:12]
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
                if auth is None:
                    return self._send(401, {"error": "UNAUTHENTICATED"})
                try:
                    self._route(u, auth)
                except GateError as e:
                    self._send(e.http, {"error": e.code})
                except Exception:
                    log.exception("unhandled")
                    self._send(500, {"error": "INTERNAL_ERROR", "outcome": "ERROR"})
            finally:
                sem.release()

        do_GET = do_POST = _dispatch

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
                        correlation_id=str(b.get("correlation_id") or self._rid), claimed_tenant=b.get("tenant_id"))
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

    return ThreadingHTTPServer((host, port), H)
