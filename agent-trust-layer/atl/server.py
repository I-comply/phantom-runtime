import hmac, json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from .gateway import Core

MAX_BODY = 1 << 20


def make_handler(core, admin_token):
    class H(BaseHTTPRequestHandler):
        server_version = "ATL"

        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            for k, v in (("Content-Type", "application/json"), ("Content-Length", str(len(b))),
                         ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(b)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("too_large")
            return json.loads(self.rfile.read(n) or b"{}")

        def _admin(self):
            return hmac.compare_digest(self.headers.get("X-ATL-Admin", "").encode(), admin_token.encode())

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/healthz":
                return self._send(200, {"ok": True})
            if not u.path.startswith("/v1/admin/") or not self._admin():
                return self._send(401, {"error": "unauthorized"})
            try:
                if u.path == "/v1/admin/events":
                    return self._send(200, {"events": core.ledger.events(q["tenant_id"], int(q.get("limit", 100)), int(q.get("after", 0)))})
                if u.path == "/v1/admin/verify":
                    return self._send(200, core.verify_all(q["tenant_id"]))
            except Exception:
                return self._send(400, {"error": "bad_request"})
            self._send(404, {"error": "not_found"})

        def do_POST(self):
            try:
                body = self._body()
            except Exception:
                return self._send(400, {"error": "bad_body"})
            if self.path == "/v1/invoke":
                r = core.invoke(body, self.client_address[0])
                return self._send(r.get("status", 200), r)
            if not self.path.startswith("/v1/admin/") or not self._admin():
                return self._send(401, {"error": "unauthorized"})
            try:
                if self.path == "/v1/admin/principals":
                    return self._send(200, core.admin_principal(body["op"], body["tenant_id"], body["principal_id"],
                                                                body.get("kind", "agent"), body.get("ttl_days")))
                if self.path == "/v1/admin/anchor":
                    return self._send(200, core.anchor(body["tenant_id"]))
            except Exception as e:
                return self._send(400, {"error": str(e)[:100]})
            self._send(404, {"error": "not_found"})
    return H


def serve(core, host="127.0.0.1", port=8787):
    tp = core.dir / "admin.token"
    if not tp.exists():
        import secrets
        fd = os.open(tp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    token = os.environ.get("ATL_ADMIN_TOKEN") or tp.read_text().strip()
    srv = ThreadingHTTPServer((host, port), make_handler(core, token))
    print(f"ATL gateway on http://{host}:{port}  admin token: {tp}")
    srv.serve_forever()
