import copy, os, subprocess, sys, json
from .util import canon, digest, norm, first_diff

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def finding(check, message, index=None, event=None, detail=None, severity="error"):
    f = {"check": check, "severity": severity, "message": message}
    if index is not None:
        f["event_index"] = index
    if event is not None:
        f["event"] = event if len(canon(event)) < 400 else canon(event)[:400] + "..."
    if detail:
        f["detail"] = detail
    return f


def fold(mod, events, upto=None):
    s = mod.initial()
    for ev in events[:upto]:
        s = mod.apply(s, ev)
    return s


def _run_worker(reducer, events, run_id, dump_at=None):
    env = dict(os.environ, PYTHONHASHSEED=str(run_id * 31 + 7), PYTHONPATH=ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
    p = subprocess.run([sys.executable, "-B", "-m", "replaycheck.worker"], input=json.dumps(
        {"reducer": os.path.abspath(reducer) if os.path.exists(reducer) else reducer, "events": events,
         "run_id": run_id, "dump_at": dump_at}), capture_output=True, text=True, env=env, timeout=300)
    if p.returncode != 0:
        raise RuntimeError("worker failed (run %d): %s" % (run_id, p.stderr.strip()[-500:]))
    return json.loads(p.stdout)


def check_determinism(reducer, events, runs=3):
    """Fold in `runs` fresh processes, each with a different hash seed, clock, RNG and uuid4 stream."""
    results = [_run_worker(reducer, events, r) for r in range(runs)]
    out = []
    for r, res in enumerate(results):
        if "error" in res:
            i = res["at"]
            out.append(finding("determinism", "reducer raised in run %d: %s" % (r, res["error"]), i, events[i - 1]))
            return out
    base = results[0]["digests"]
    bad = None
    for r in range(1, runs):
        d = results[r]["digests"]
        for i in range(len(base)):
            if base[i] != d[i]:
                bad = i + 1 if bad is None else min(bad, i + 1)
                break
    if bad is not None:
        a = _run_worker(reducer, events, 0, bad)["dump"]
        where = None
        for r in range(1, runs):
            b = _run_worker(reducer, events, r, bad)["dump"]
            where = first_diff(a, b)
            if where:
                break
        out.append(finding("determinism", "state diverges between runs with different hash seed/clock/RNG/uuid",
                           bad, events[bad - 1], "first differing field: %s" % where))
    return out


def check_event_mutation(mod, events):
    out, s = [], mod.initial()
    for i, ev in enumerate(events, 1):
        before = canon(ev)
        try:
            s = mod.apply(s, ev)
        except Exception as e:
            return out + [finding("reducer", "apply() raised %s: %s" % (type(e).__name__, e), i, ev)]
        if canon(ev) != before:
            out.append(finding("event-mutation", "apply() mutated its input event", i, ev))
            break
        try:
            canon(s)
        except (TypeError, ValueError) as e:
            out.append(finding("state-type", "state is not canonical JSON: %s" % e, i, ev))
            break
    return out


def check_snapshots(mod, events, snaps):
    out, s, n, want = [], mod.initial(), 0, dict(snaps)
    if any(k > len(events) or k < 0 for k in want):
        out.append(finding("snapshot", "snapshot seq beyond event count %d: %s" % (
            len(events), sorted(k for k in want if k > len(events) or k < 0))))
    for i, ev in enumerate(events, 1):
        s = mod.apply(s, ev)
        if i in want:
            where = first_diff(norm(s), norm(want[i]))
            if where:
                out.append(finding("snapshot", "snapshot at n=%d differs from replay" % i, i, ev,
                                   "first differing field: %s" % where))
    return out


def check_projection(proj, events, live):
    rebuilt = norm(proj.rebuild(events))
    if callable(getattr(proj, "normalize_live", None)):
        live = proj.normalize_live(live)
    where = first_diff(rebuilt, norm(live))
    if not where:
        return []
    return [finding("projection", "live projection differs from rebuild from scratch", None, None,
                    "first differing field: %s" % where)]


def check_upcast(up, events):
    out = []
    for i, ev in enumerate(events, 1):
        before = canon(ev)
        probe = copy.deepcopy(ev)
        once = up.upcast(probe)
        if canon(probe) != before:
            out.append(finding("upcast", "upcast() mutates its input event", i, ev, severity="warning"))
        twice = up.upcast(copy.deepcopy(once))
        where = first_diff(norm(once), norm(twice))
        if where:
            out.append(finding("upcast", "upcast is not idempotent (upcast(upcast(e)) != upcast(e))", i, ev,
                               "first differing field: %s" % where))
            break
        if callable(getattr(up, "validate", None)):
            errs = up.validate(once)
            if errs:
                out.append(finding("upcast", "upcasted event fails validation", i, ev, "; ".join(map(str, errs))[:300]))
                break
    return out
