"""CLI: python -m ctal {demo|serve|migrate|create-api-key|export-pubkey|release-manifest|release-verify}."""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ctal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="run the end-to-end local demonstration (temp dir, dev keys)")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--tls-cert")
    s.add_argument("--tls-key")
    s.add_argument("--behind-tls-proxy", action="store_true", help="production only: assert TLS is terminated in front")
    s.add_argument("--rate-limit", default="60,20", help="capacity,refill_per_second per API key; 'off' disables")
    m = sub.add_parser("migrate")
    m.add_argument("direction", choices=["up", "down"])
    m.add_argument("--version", default="0001_init")
    k = sub.add_parser("create-api-key")
    k.add_argument("tenant")
    k.add_argument("role", choices=["gate", "auditor", "reviewer", "admin"])
    k.add_argument("label")
    r = sub.add_parser("release-manifest", help="write a signed release manifest + SBOM (export key)")
    r.add_argument("--out", required=True)
    v = sub.add_parser("release-verify", help="verify a release manifest against a pinned export key and this source tree")
    v.add_argument("manifest")
    v.add_argument("--pin-export-key-id", required=True)
    v.add_argument("--pin-export-public-key", required=True)
    sub.add_parser("export-pubkey", help="print export key id + public key (for pinning in the offline verifier)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    if a.cmd == "demo":
        from .demo import run_demo
        return run_demo()
    from .config import build_from_env
    gate, xs, public = build_from_env()
    if a.cmd == "serve":
        import os
        from .server import make_server
        tls = (a.tls_cert, a.tls_key) if a.tls_cert and a.tls_key else None
        if os.environ.get("CTAL_ENV") == "production" and not tls and not a.behind_tls_proxy:
            print("refusing to serve in production without --tls-cert/--tls-key or --behind-tls-proxy", file=sys.stderr)
            return 2
        rl = None if a.rate_limit == "off" else tuple(float(x) for x in a.rate_limit.split(","))
        srv = make_server(a.host, a.port, gate, xs, public, rate_limit=(int(rl[0]), rl[1]) if rl else None, tls=tls)
        print("ctal listening on %s:%d" % (a.host, a.port), file=sys.stderr)
        srv.serve_forever()
    elif a.cmd == "migrate":
        (gate.store.migrate_up if a.direction == "up" else lambda: gate.store.migrate_down(a.version))()
    elif a.cmd == "create-api-key":
        print(gate.store.create_api_key(a.tenant, a.role, a.label))
    elif a.cmd == "release-manifest":
        import json
        from .release import build_manifest
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(build_manifest(xs), f, indent=2)
        print("wrote", a.out)
    elif a.cmd == "release-verify":
        import json
        from .keys import TrustStore, TrustedKey, unb64u
        from .release import verify_manifest
        t = TrustStore()
        t.add(TrustedKey(a.pin_export_key_id, unb64u(a.pin_export_public_key), "export"))
        with open(a.manifest, encoding="utf-8") as f:
            res = verify_manifest(json.load(f), t)
        print(json.dumps(res))
        return 0 if res["ok"] else 1
    elif a.cmd == "export-pubkey":
        from .keys import b64u
        print(xs.key_id, b64u(xs.public_raw()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
