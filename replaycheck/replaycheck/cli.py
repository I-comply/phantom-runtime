import argparse, json, sys
from . import __version__
from .checks import (check_determinism, check_event_mutation, check_snapshots, check_projection, check_upcast, finding)
from .store import load_events, load_snapshots, load_live
from .util import load_module, need


def build_parser():
    p = argparse.ArgumentParser(prog="replaycheck", description="Audit an event-sourced system: does state == fold(events), every time?")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the checks")
    r.add_argument("--store", required=True, help="events: JSONL file or SQLite file")
    r.add_argument("--table", default="events")
    r.add_argument("--payload-col", default="payload")
    r.add_argument("--order-col", default="rowid")
    r.add_argument("--reducer", required=True, help="module or .py file defining initial() and apply(state, event)")
    r.add_argument("--runs", type=int, default=3, help="fresh-process replays for the determinism check (>=2)")
    r.add_argument("--snapshots", help="JSONL {seq,state} or SQLite file; seq = number of events applied")
    r.add_argument("--snapshot-table", default="snapshots")
    r.add_argument("--projection", help="module defining rebuild(events) [and optional normalize_live(raw)]")
    r.add_argument("--live", help="live projection: JSON file, or SQLite file with --live-query")
    r.add_argument("--live-query")
    r.add_argument("--upcast", help="module defining upcast(event) [and optional validate(event)->list of errors]")
    r.add_argument("--format", choices=["text", "json"], default="text")
    return p


def run(a):
    if a.runs < 2:
        raise SystemExit("error: --runs must be >= 2")
    events = load_events(a.store, a.table, a.payload_col, a.order_col)
    mod = load_module(a.reducer)
    need(mod, "initial", "apply")
    findings, checks = [], []
    checks.append("event-mutation")
    findings += check_event_mutation(mod, events)
    if not any(f["check"] in ("reducer", "state-type") for f in findings):
        checks.append("determinism")
        findings += check_determinism(a.reducer, events, a.runs)
    if a.snapshots:
        checks.append("snapshot")
        findings += check_snapshots(mod, events, load_snapshots(a.snapshots, a.snapshot_table))
    if a.projection:
        if not a.live:
            raise SystemExit("error: --projection needs --live")
        pm = load_module(a.projection)
        need(pm, "rebuild")
        checks.append("projection")
        findings += check_projection(pm, events, load_live(a.live, a.live_query))
    if a.upcast:
        um = load_module(a.upcast)
        need(um, "upcast")
        checks.append("upcast")
        findings += check_upcast(um, events)
    return {"events": len(events), "checks": checks, "findings": findings,
            "ok": not any(f["severity"] == "error" for f in findings)}


def render(rep):
    lines = ["replaycheck: %d events, checks: %s" % (rep["events"], ", ".join(rep["checks"]))]
    for f in rep["findings"]:
        loc = " at event #%d" % f["event_index"] if "event_index" in f else ""
        lines.append("%s [%s]%s: %s" % (f["severity"].upper(), f["check"], loc, f["message"]))
        if "detail" in f:
            lines.append("    %s" % f["detail"])
        if "event" in f:
            lines.append("    event: %s" % json.dumps(f["event"], sort_keys=True)[:300])
    lines.append("PASS" if rep["ok"] else "FAIL")
    return "\n".join(lines)


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        rep = run(a)
    except SystemExit:
        raise
    except Exception as e:
        print("error: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=2, sort_keys=True) if a.format == "json" else render(rep))
    return 0 if rep["ok"] else 1
