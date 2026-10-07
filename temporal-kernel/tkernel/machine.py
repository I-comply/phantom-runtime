import json
from .util import canon, sha256


class MachineError(ValueError):
    pass


class Machine:
    """Declarative state machine. Every non-terminal state owns exactly one task; a task result
    names a trigger which selects the next state. Pure data: no callbacks, so replay is deterministic.

    {"id": "order", "initial": "reserve",
     "states": {"reserve": {"task": "reserve_stock", "max_attempts": 3, "on": {"ok": "charge"}},
                "charge":  {"task": "charge_card", "on": {"ok": "done", "declined": "failed"}},
                "done": {"terminal": true}, "failed": {"terminal": true}}}
    """

    def __init__(self, spec):
        spec = json.loads(canon(spec))  # deep copy; rejects NaN / non-JSON
        self.spec = spec
        self.id = spec.get("id")
        self.initial = spec.get("initial")
        self.states = spec.get("states")
        if not isinstance(self.id, str) or not self.id:
            raise MachineError("id required")
        if not isinstance(self.states, dict) or not self.states:
            raise MachineError("states required")
        if self.initial not in self.states:
            raise MachineError("initial state unknown")
        for name, s in self.states.items():
            if s.get("terminal"):
                if "task" in s or "on" in s:
                    raise MachineError("terminal state %s must not have task/on" % name)
                continue
            if not isinstance(s.get("task"), str) or not s["task"]:
                raise MachineError("state %s needs a task" % name)
            on = s.get("on")
            if not isinstance(on, dict) or not on:
                raise MachineError("state %s needs transitions" % name)
            for trig, tgt in on.items():
                if tgt not in self.states:
                    raise MachineError("state %s: trigger %s -> unknown state %s" % (name, trig, tgt))
            if int(s.get("max_attempts", 1)) < 1:
                raise MachineError("state %s: max_attempts < 1" % name)
        self.hash = sha256(canon(spec))

    def terminal(self, state):
        return bool(self.states[state].get("terminal"))

    def max_attempts(self, state):
        return int(self.states[state].get("max_attempts", 1))
