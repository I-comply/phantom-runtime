import sys, tempfile, os
from . import EventLog, Machine, Node

SPEC = {"id": "order", "initial": "reserve", "states": {
    "reserve": {"task": "reserve_stock", "max_attempts": 2, "on": {"ok": "charge"}},
    "charge": {"task": "charge_card", "on": {"ok": "done", "declined": "failed"}},
    "done": {"terminal": True}, "failed": {"terminal": True}}}


def demo():
    db = os.path.join(tempfile.mkdtemp(), "log.db")
    t = [0]
    clock = lambda: t[0]
    m = Machine(SPEC)
    a = Node(EventLog(db), [m], "A", lease_ms=1000, clock=clock)
    b = Node(EventLog(db), [m], "B", lease_ms=1000, clock=clock)
    a.start("w1", "order", {"sku": 1})
    task = a.claim("w1"); a.complete("w1", task["task_id"], task["fence"], "ok")
    cp = a.checkpoint("w1", "reserved")
    task = a.claim("w1"); print("A leased", task["name"], "fence", task["fence"])
    t[0] += 1500; print("node A dies; B recovers")
    task = b.claim("w1"); print("B leased", task["name"], "fence", task["fence"])
    b.rollback("w1", cp["seq"], "operator"); b.resume("w1")
    task = b.claim("w1"); b.complete("w1", task["task_id"], task["fence"], "ok")
    print("final", b.state("w1")["mstate"], "events", b.verify("w1"))


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    elif len(sys.argv) == 4 and sys.argv[1] == "verify":  # verify <db> <wf_id>; exit 1 on corruption
        try:
            print(EventLog(sys.argv[2]).verify(sys.argv[3]))
        except Exception as ex:
            sys.exit("INTEGRITY FAILURE: %s" % ex)
    else:
        sys.exit("usage: python3 -m tkernel demo | verify <db> <wf_id>")
