import copy
from .util import canon, sha256


class InvalidEvent(Exception):
    """Event is not legal in the current state (rejected as a command, fatal during replay)."""


class ReplayDivergence(Exception):
    """A checkpoint hash disagrees with the state recomputed from the log."""


def core_hash(state):
    return sha256(canon({k: v for k, v in state.items() if k != "checkpoints"}))


class Replay:
    """Pure fold of an event stream into workflow state. No clock, randomness or I/O: everything
    time-dependent (lease expiry, fences) is carried in event payloads, so any node replaying the
    same log reaches the same state."""

    def __init__(self, machine):
        self.m = machine
        self.state = None
        self.snaps = {}  # checkpoint seq -> state after that checkpoint
        self.seq = 0

    def clone(self):
        r = Replay(self.m)
        r.state, r.snaps, r.seq = copy.deepcopy(self.state), dict(self.snaps), self.seq
        return r

    # ---- helpers
    def _enter(self, s, name):
        s["mstate"] = name
        if self.m.terminal(name):
            s["status"] = "completed"
            return
        s["task_seq"] += 1
        tid = "t%d" % s["task_seq"]
        s["tasks"][tid] = {"name": self.m.states[name]["task"], "state": name, "status": "pending",
                           "attempts": 0, "fence": 0, "node": None, "expires": 0}
        s["active"] = tid

    def _task(self, s, p, want):
        t = s["tasks"].get(p.get("task_id"))
        if t is None or s["active"] != p["task_id"]:
            raise InvalidEvent("task %s is not the active task" % p.get("task_id"))
        if t["status"] != want:
            raise InvalidEvent("task %s is %s, need %s" % (p["task_id"], t["status"], want))
        return t

    def _live(self, s):
        if s["status"] not in ("running", "paused"):
            raise InvalidEvent("workflow is %s" % s["status"])

    # ---- reducer
    def apply(self, e):
        t, p, s = e["type"], e["payload"], self.state
        if t == "wf.started":
            if s is not None:
                raise InvalidEvent("already started")
            if p.get("machine_hash") != self.m.hash:
                raise InvalidEvent("machine definition does not match the one the workflow started with")
            s = self.state = {"machine": self.m.id, "status": "running", "mstate": None, "ctx": {},
                              "input": p.get("input"), "tasks": {}, "active": None, "task_seq": 0,
                              "fence": 0, "checkpoints": []}
            self._enter(s, self.m.initial)
        elif s is None:
            raise InvalidEvent("workflow not started")
        elif t == "task.leased":
            self._live(s)
            if s["status"] != "running":
                raise InvalidEvent("paused")
            tk = self._task(s, p, "pending")
            if p["fence"] != s["fence"] + 1:
                raise InvalidEvent("fence must be %d" % (s["fence"] + 1))
            tk.update(status="leased", node=p["node"], expires=p["expires"], fence=p["fence"])
            s["fence"] = p["fence"]
        elif t in ("task.heartbeat", "task.completed", "task.failed", "task.lease_expired"):
            self._live(s)
            tk = self._task(s, p, "leased")
            if tk["fence"] != p.get("fence"):
                raise InvalidEvent("stale fence %s (current %s)" % (p.get("fence"), tk["fence"]))
            if t == "task.heartbeat":
                tk["expires"] = p["expires"]
            elif t == "task.lease_expired":
                tk.update(status="pending", node=None, expires=0)
            elif t == "task.failed":
                tk["attempts"] += 1
                tk.update(node=None, expires=0)
                if tk["attempts"] >= self.m.max_attempts(tk["state"]):
                    tk["status"] = "failed"
                    s["status"] = "failed"
                    s["error"] = p.get("error")
                else:
                    tk["status"] = "pending"
            else:  # completed
                nxt = self.m.states[tk["state"]]["on"].get(p.get("trigger"))
                if nxt is None:
                    raise InvalidEvent("trigger %r not allowed in %s" % (p.get("trigger"), tk["state"]))
                tk["status"] = "done"
                s["ctx"][tk["name"]] = p.get("result")
                self._enter(s, nxt)
        elif t == "wf.paused":
            if s["status"] != "running":
                raise InvalidEvent("cannot pause a %s workflow" % s["status"])
            s["status"] = "paused"
        elif t == "wf.resumed":
            if s["status"] != "paused":
                raise InvalidEvent("workflow is not paused")
            s["status"] = "running"
        elif t == "checkpoint":
            self._live(s)
            if p.get("state_hash") != core_hash(s):
                raise ReplayDivergence("checkpoint at seq %d: state hash mismatch" % e["seq"])
            s["checkpoints"].append(e["seq"])
            self.snaps[e["seq"]] = copy.deepcopy(s)
        elif t == "wf.rolled_back":
            self._live(s)
            to = p.get("to_seq")
            if to not in s["checkpoints"]:
                raise InvalidEvent("seq %r is not a live checkpoint" % (to,))
            r = copy.deepcopy(self.snaps[to])
            r["checkpoints"] = [c for c in s["checkpoints"] if c <= to]
            r["fence"] = s["fence"]  # fences never go backwards: workers from the discarded branch stay stale
            r["status"] = "paused"   # operator must inspect then resume
            for tk in r["tasks"].values():
                if tk["status"] == "leased":
                    tk.update(status="pending", node=None, expires=0)
            self.state = r
        else:
            raise InvalidEvent("unknown event type %s" % t)

    def feed(self, events):
        for e in events:
            self.apply(e)
            self.seq = e["seq"]
        return self
