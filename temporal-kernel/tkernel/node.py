import json, uuid
from .util import canon
from .eventlog import Conflict
from .replay import Replay, InvalidEvent, core_hash
from .util import now_ms


class Rejected(Exception):
    """Command refused; nothing was appended."""


class Node:
    """A kernel node. Stateless apart from a replay cache: all authority lives in the shared log, so
    any node can resume any workflow after another node dies. Commands are decide -> dry-run apply
    -> append(expected_seq); on Conflict the node reloads and re-decides."""

    def __init__(self, log, machines, node_id=None, lease_ms=30_000, clock=now_ms, retries=20):
        self.log, self.id, self.lease_ms, self.clock, self.retries = log, node_id or uuid.uuid4().hex[:8], lease_ms, clock, retries
        self.machines = {m.id: m for m in machines}
        self._cache = {}

    # ---- loading
    def _load(self, wf):
        r = self._cache.get(wf)
        if r is None:
            evs = self.log.read(wf)
            if not evs:
                raise Rejected("unknown workflow %s" % wf)
            if evs[0]["type"] != "wf.started":
                raise Rejected("stream %s does not start with wf.started" % wf)
            mid = evs[0]["payload"].get("machine")
            if mid not in self.machines:
                raise Rejected("no machine %r registered" % mid)
            r = Replay(self.machines[mid])
            r.feed(evs)
            self._cache[wf] = r
        else:
            r.feed(self.log.read(wf, r.seq))
        return r

    def state(self, wf):
        import copy
        return copy.deepcopy(self._load(wf).state)

    def _commit(self, wf, build, idem=None):
        """build(replay) -> list[(type,payload)] or None for a no-op. Appends atomically per event."""
        last = None
        for _ in range(self.retries):
            r = self._load(wf)
            trial = r.clone()
            plan = build(trial)
            if not plan:
                return None
            try:
                for i, (t, p) in enumerate(plan):
                    trial.apply({"type": t, "payload": p, "seq": trial.seq + 1})
                    trial.seq += 1
            except InvalidEvent as ex:
                raise Rejected(str(ex))
            out = []
            try:
                for i, (t, p) in enumerate(plan):
                    out.append(self.log.append(wf, r.seq + i, t, p, idem=("%s#%d" % (idem, i)) if idem else None,
                                               ts=self.clock()))
                self._cache.pop(wf, None)
                return out
            except Conflict as ex:
                last = ex
                if out:  # partial multi-event plan: cannot happen with single-event plans below
                    raise
        raise Rejected("too much contention: %s" % last)

    # ---- commands
    def start(self, wf, machine_id, input=None):
        m = self.machines[machine_id]
        payload = {"machine": m.id, "machine_hash": m.hash, "input": input}
        try:
            e = self.log.append(wf, 0, "wf.started", payload, idem="start", ts=self.clock())
            if e.get("duplicate") and e["payload"] != json.loads(canon(payload)):
                raise Rejected("workflow %s already exists with different parameters" % wf)
        except Conflict:
            raise Rejected("workflow %s already exists" % wf)
        self._cache.pop(wf, None)
        return e

    def claim(self, wf):
        """Lease the active task (recovering an expired lease first). Returns task dict or None."""
        def build(r):
            s, now = r.state, self.clock()
            if s["status"] != "running" or not s["active"]:
                return None
            t = s["tasks"][s["active"]]
            if t["status"] == "leased":
                if t["expires"] > now:
                    return None
                return [("task.lease_expired", {"task_id": s["active"], "fence": t["fence"]})]
            if t["status"] != "pending":
                return None
            return [("task.leased", {"task_id": s["active"], "node": self.id, "fence": s["fence"] + 1,
                                     "expires": now + self.lease_ms})]
        for _ in range(3):  # at most: expire, then lease
            out = self._commit(wf, build)
            if out is None:
                return None
            if out[0]["type"] == "task.leased":
                s, p = self._load(wf).state, out[0]["payload"]
                t = s["tasks"][p["task_id"]]
                return {"task_id": p["task_id"], "name": t["name"], "fence": p["fence"],
                        "attempt": t["attempts"] + 1, "input": s["input"], "ctx": s["ctx"]}
        return None

    def _task_cmd(self, wf, etype, task_id, fence, extra):
        def build(r):
            p = {"task_id": task_id, "fence": fence}
            p.update(extra(r) if callable(extra) else extra)
            return [(etype, p)]
        return self._commit(wf, build)[0]

    def heartbeat(self, wf, task_id, fence):
        return self._task_cmd(wf, "task.heartbeat", task_id, fence, lambda r: {"expires": self.clock() + self.lease_ms})

    def complete(self, wf, task_id, fence, trigger, result=None):
        return self._task_cmd(wf, "task.completed", task_id, fence, {"trigger": trigger, "result": result})

    def fail(self, wf, task_id, fence, error):
        return self._task_cmd(wf, "task.failed", task_id, fence, {"error": error})

    def pause(self, wf, reason=None):
        return self._commit(wf, lambda r: [("wf.paused", {"reason": reason})])[0]

    def resume(self, wf, reason=None):
        return self._commit(wf, lambda r: [("wf.resumed", {"reason": reason})])[0]

    def checkpoint(self, wf, label=None):
        return self._commit(wf, lambda r: [("checkpoint", {"state_hash": core_hash(r.state), "label": label})])[0]

    def rollback(self, wf, to_seq, reason=None):
        """Logical rollback: appends wf.rolled_back (history is never rewritten). Leaves the workflow paused."""
        return self._commit(wf, lambda r: [("wf.rolled_back", {"to_seq": to_seq, "reason": reason})])[0]

    def recover(self, wf):
        """Expire an overdue lease so another node can claim the task."""
        def build(r):
            s = r.state
            t = s["tasks"].get(s["active"]) if s["active"] else None
            if s["status"] in ("running", "paused") and t and t["status"] == "leased" and t["expires"] <= self.clock():
                return [("task.lease_expired", {"task_id": s["active"], "fence": t["fence"]})]
            return None
        out = self._commit(wf, build)
        return out[0] if out else None

    def verify(self, wf):
        """Chain check, then full replay (checkpoint hashes re-derived). Returns head seq."""
        n = self.log.verify(wf)
        evs = self.log.read(wf)
        r = Replay(self.machines[evs[0]["payload"]["machine"]])
        r.feed(evs)
        return n
