"""Agent success-test harness. Spawns N agent processes per tenant against a live ATL gateway (HTTP),
each running honest and adversarial scenarios with an expected outcome; then verifies every ledger.
Usage: python3 -m harness.run_agents [--tenants 3] [--agents 8] [--executor subprocess|docker] [--out reports]"""
import argparse, json, multiprocessing as mp, os, shutil, statistics, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from atl.client import sign_request, sign_approval
from atl.util import now_ms


def post(base, body, path="/v1/invoke", admin=None):
    h = {"Content-Type": "application/json"}
    if admin:
        h["X-ATL-Admin"] = admin
    r = urllib.request.Request(base + path, json.dumps(body).encode(), h)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(r, timeout=60) as f:
            code, out = f.status, json.loads(f.read())
    except urllib.error.HTTPError as e:
        code, out = e.code, json.loads(e.read() or b"{}")
    return code, out, (time.perf_counter() - t0) * 1000


def agent_main(args):
    base, tenant, aid, sec, other_sec, appr = args
    rec, rid = [], 0

    def go(scn, exp, req, extra=None):
        code, out, ms = post(base, req)
        rec.append({"agent": f"{tenant}/{aid}", "scenario": scn, "expected": exp, "status": code,
                    "ok": code == exp, "ms": ms})
        return code, out

    S = lambda act, p, **k: sign_request(sec, tenant, aid, 1, act, p, **k)
    go("honest_echo", 200, S("echo", {"text": "hi"}))
    go("honest_hash", 200, S("hash_text", {"text": "abc"}))
    go("honest_write", 200, S("fs_write", {"path": f"{aid}.txt", "content": "data"}))
    go("honest_read", 200, S("fs_read", {"path": f"{aid}.txt"}))
    q = S("echo", {"text": "r"}); go("replay_first", 200, q); go("replay_second", 401, q)
    bad = S("echo", {"text": "x"}); bad["signature"] = "0" * 64; go("forged_signature", 401, bad)
    go("cross_tenant_secret", 401, sign_request(other_sec, tenant, aid, 1, "echo", {"text": "x"}))
    go("unknown_tool", 403, S("rm_rf", {}))
    go("param_injection", 403, S("echo", {"text": "x", "extra": 1}))
    go("path_traversal", 502, S("fs_read", {"path": "../../etc/passwd"}))
    go("absolute_path", 502, S("fs_read", {"path": "/etc/passwd"}))
    go("oversize_param", 403, S("echo", {"text": "A" * 5000}))
    go("stale_timestamp", 401, S("echo", {"text": "x"}, ts=now_ms() - 3_600_000))
    go("destructive_no_approval", 403, S("fs_delete", {"path": f"{aid}.txt"}))
    p = {"path": f"{aid}.txt"}
    ap = sign_approval(appr, tenant, "boss", 1, aid, "fs_delete", p, now_ms() + 60000)
    go("destructive_approved", 200, S("fs_delete", p, approval=ap))
    go("approval_reuse", 403, S("fs_delete", p, approval=ap))
    ap2 = sign_approval(appr, tenant, "boss", 1, aid, "fs_delete", {"path": "other"}, now_ms() + 60000)
    go("approval_wrong_intent", 403, S("fs_delete", p, approval=ap2))
    go("idem_first", 200, S("echo", {"text": "i"}, idempotency_key=f"k-{aid}"))
    go("idem_replay", 200, S("echo", {"text": "i"}, idempotency_key=f"k-{aid}"))
    go("idem_reuse_diff_params", 400, S("echo", {"text": "j"}, idempotency_key=f"k-{aid}"))
    for i in range(10):
        go("burst_echo", 200, S("echo", {"text": str(i)}))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", type=int, default=3)
    ap.add_argument("--agents", type=int, default=8)
    ap.add_argument("--executor", default="subprocess")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    os.environ["ATL_EXECUTOR"] = a.executor
    from atl.gateway import Core
    from atl.server import make_handler
    d = Path(tempfile.mkdtemp(prefix="atl-harness-"))
    shutil.copy(ROOT / "capabilities.json", d / "capabilities.json")
    core = Core(d)
    # per-agent rate limit is 60/min; harness stays under it (34 calls/agent)
    tenants = [f"t{i}" for i in range(a.tenants)]
    jobs, secrets_ = [], {}
    for t in tenants:
        secrets_[t] = {x: core.admin_principal("issue", t, x) for x in [f"a{i}" for i in range(a.agents)]}
        for p in secrets_[t].values():
            pass
        secrets_[t]["boss"] = core.admin_principal("issue", t, "boss", "approver")
    # writer grant is by agent id in manifest; give harness agents write+delete
    m = json.loads((d / "capabilities.json").read_text())
    for t in tenants:
        for i in range(a.agents):
            m["grants"][f"a{i}"] = ["fs_write", "fs_delete"]
    (d / "capabilities.json").write_text(json.dumps(m))
    from atl.policy import Policy
    core.policy = Policy.load(d / "capabilities.json")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(core, "adm"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    for ti, t in enumerate(tenants):
        other = secrets_[tenants[(ti + 1) % len(tenants)]]
        for i in range(a.agents):
            jobs.append((base, t, f"a{i}", secrets_[t][f"a{i}"]["secret"], other[f"a{i}"]["secret"], secrets_[t]["boss"]["secret"]))
    t0 = time.perf_counter()
    with mp.Pool(len(jobs)) as pool:
        res = pool.map(agent_main, jobs)
    wall = time.perf_counter() - t0
    recs = [r for x in res for r in x]
    ver = {t: core.verify_all(t) for t in tenants}
    # attacker rate-limit check: forged signatures from one source get throttled, victim unaffected
    for _ in range(40):
        bad = sign_request("00" * 32, tenants[0], "a0", 1, "echo", {"text": "x"})
        core.invoke(bad, src="6.6.6.6")
    throttled = core.invoke(sign_request(secrets_[tenants[0]]["a0"]["secret"], tenants[0], "a0", 1, "echo", {"text": "x"}), src="6.6.6.6")["status"]
    anchor = core.anchor(tenants[0])
    # tamper detection
    core.db.conn().executescript("DROP TRIGGER events_no_update;")
    core.db.conn().execute("UPDATE events SET payload='{\"x\":1}' WHERE tenant_id=? AND seq=3", (tenants[0],))
    tamper = core.verify_all(tenants[0])
    events = {t: len(core.ledger.events(t, 10 ** 9)) for t in tenants if t != tenants[0]}
    srv.shutdown()
    out = Path(a.out); out.mkdir(exist_ok=True)
    summary = {"executor": a.executor, "tenants": a.tenants, "agents_per_tenant": a.agents,
               "agent_instances": len(jobs), "requests": len(recs), "wall_s": round(wall, 2),
               "throughput_rps": round(len(recs) / wall, 1),
               "pass": sum(r["ok"] for r in recs), "fail": sum(not r["ok"] for r in recs),
               "ledger_verify": {t: v["ok"] for t, v in ver.items()}, "events": {t: v["count"] for t, v in ver.items()},
               "rate_limit_attacker_status": throttled, "tamper_detected": not tamper["ok"], "tamper_error": tamper["error"],
               "anchor_seq": anchor["seq"]}
    ms = sorted(r["ms"] for r in recs)
    summary["latency_ms"] = {"p50": round(statistics.median(ms), 1), "p95": round(ms[int(len(ms) * .95)], 1),
                             "p99": round(ms[int(len(ms) * .99)], 1), "max": round(ms[-1], 1)}
    tag = a.executor
    (out / f"results_{tag}.json").write_text(json.dumps({"summary": summary, "records": recs}, indent=1))
    print(json.dumps(summary, indent=1))
    shutil.rmtree(d, ignore_errors=True)
    sys.exit(0 if summary["fail"] == 0 and all(summary["ledger_verify"].values()) and summary["tamper_detected"] else 1)


if __name__ == "__main__":
    main()
