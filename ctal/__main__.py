"""CLI: python -m ctal {demo|serve|migrate|create-api-key|export-pubkey}."""
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
    m = sub.add_parser("migrate")
    m.add_argument("direction", choices=["up", "down"])
    m.add_argument("--version", default="0001_init")
    k = sub.add_parser("create-api-key")
    k.add_argument("tenant")
    k.add_argument("role", choices=["gate", "auditor", "admin"])
    k.add_argument("label")
    sub.add_parser("export-pubkey", help="print export key id + public key (for pinning in the offline verifier)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    if a.cmd == "demo":
        from .demo import run_demo
        return run_demo()
    from .config import build_from_env
    gate, xs, public = build_from_env()
    if a.cmd == "serve":
        from .server import make_server
        srv = make_server(a.host, a.port, gate, xs, public)
        print("ctal listening on %s:%d" % (a.host, a.port), file=sys.stderr)
        srv.serve_forever()
    elif a.cmd == "migrate":
        (gate.store.migrate_up if a.direction == "up" else lambda: gate.store.migrate_down(a.version))()
    elif a.cmd == "create-api-key":
        print(gate.store.create_api_key(a.tenant, a.role, a.label))
    elif a.cmd == "export-pubkey":
        from .keys import b64u
        print(xs.key_id, b64u(xs.public_raw()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
