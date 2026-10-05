import argparse, json, os, shutil, sqlite3, sys, tempfile
from pathlib import Path
from .gateway import Core
from .ledger import verify_conn
from .client import sign_request, sign_approval
from .util import now_ms

ROOT = Path(__file__).resolve().parent.parent


def core(a):
    d = Path(a.dir)
    if not (d / "capabilities.json").exists():
        sys.exit("run: atl init")
    return Core(d)


def pj(o):
    print(json.dumps(o, indent=2, sort_keys=True))


def demo():
    d = Path(tempfile.mkdtemp(prefix="atl-demo-"))
    shutil.copy(ROOT / "capabilities.json", d / "capabilities.json")
    c = Core(d)
    T = "acme"
    ag = c.admin_principal("issue", T, "writer")
    ap = c.admin_principal("issue", T, "alice", "approver")
    S = ag["secret"]
    steps = []

    def step(name, r):
        steps.append((name, r.get("status"), r.get("decision") or r.get("error"), r.get("reason", "")))

    step("fs_write", c.invoke(sign_request(S, T, "writer", 1, "fs_write", {"path": "a.txt", "content": "hi"})))
    p = {"path": "a.txt"}
    r = c.invoke(sign_request(S, T, "writer", 1, "fs_delete", p))
    step("fs_delete (no approval)", r)
    appr = sign_approval(ap["secret"], T, "alice", 1, "writer", "fs_delete", p, now_ms() + 60000)
    step("fs_delete (approved)", c.invoke(sign_request(S, T, "writer", 1, "fs_delete", p, approval=appr)))
    rq = sign_request(S, T, "writer", 1, "echo", {"text": "x"})
    c.invoke(rq)
    step("replay", c.invoke(rq))
    c.admin_principal("revoke", T, "writer")
    step("revoked agent", c.invoke(sign_request(S, T, "writer", 1, "echo", {"text": "x"})))
    for s in steps:
        print(f"{s[0]:28} status={s[1]} {s[2]} {s[3]}")
    c.anchor(T)
    print("verify:", c.verify_all(T))
    c.db.conn().executescript("DROP TRIGGER events_no_update;")
    c.db.conn().execute("UPDATE events SET payload='{\"tampered\":1}' WHERE tenant_id='acme' AND seq=3")
    print("after tamper:", c.verify_all(T))
    shutil.rmtree(d, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(prog="atl")
    p.add_argument("--dir", default=os.environ.get("ATL_DIR", "./atl-data"))
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("init")
    pr = s.add_parser("principal")
    pr.add_argument("op", choices=["issue", "rotate", "revoke"])
    pr.add_argument("tenant")
    pr.add_argument("id")
    pr.add_argument("--kind", default="agent", choices=["agent", "approver"])
    pr.add_argument("--ttl-days", type=float)
    sv = s.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8787)
    s.add_parser("mcp")
    v = s.add_parser("verify")
    v.add_argument("tenant")
    v.add_argument("--chain-only", action="store_true", help="offline: no master key needed")
    an = s.add_parser("anchor")
    an.add_argument("tenant")
    ev = s.add_parser("events")
    ev.add_argument("tenant")
    ev.add_argument("--limit", type=int, default=50)
    ky = s.add_parser("key")
    ky.add_argument("op", choices=["rotate", "status"])
    s.add_parser("demo")
    a = p.parse_args(argv)
    if a.cmd == "init":
        d = Path(a.dir)
        d.mkdir(parents=True, exist_ok=True)
        if not (d / "capabilities.json").exists():
            shutil.copy(ROOT / "capabilities.json", d / "capabilities.json")
        Core(d)
        print(f"initialized {d}")
    elif a.cmd == "demo":
        demo()
    elif a.cmd == "mcp":
        from . import mcp
        mcp.main()
    elif a.cmd == "verify" and a.chain_only:
        conn = sqlite3.connect(f"file:{Path(a.dir) / 'atl.db'}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        r = verify_conn(conn, a.tenant)
        pj(r)
        sys.exit(0 if r["ok"] else 1)
    else:
        c = core(a)
        if a.cmd == "principal":
            pj(c.admin_principal(a.op, a.tenant, a.id, a.kind, a.ttl_days))
        elif a.cmd == "serve":
            from .server import serve
            serve(c, a.host, a.port)
        elif a.cmd == "verify":
            r = c.verify_all(a.tenant)
            pj(r)
            sys.exit(0 if r["ok"] else 1)
        elif a.cmd == "key":
            pj(c.rotate_master() if a.op == "rotate"
               else {"provider": c.keys.name, "master_version": c.keys.current_version()})
        elif a.cmd == "anchor":
            pj(c.anchor(a.tenant))
        elif a.cmd == "events":
            pj(c.ledger.events(a.tenant, a.limit))
