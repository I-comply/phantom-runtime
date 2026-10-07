import fnmatch, json, re
from pathlib import Path

TYPES = {"string": str, "integer": int, "boolean": bool, "number": (int, float)}


class PolicyError(Exception):
    pass


class Policy:
    """Capability manifest + grants. Default deny. Any malformed manifest raises (fail closed)."""

    def __init__(self, doc):
        try:
            if doc.get("version") != 1:
                raise PolicyError("manifest version must be 1")
            self.tools, self.grants = doc["tools"], doc["grants"]
            self.limits = {"per_minute": 60, "approval_ttl_s": 900, "timeout_s": 10, "skew_s": 60,
                           "idem_lease_s": 120}  # a request still in_progress after this is treated as abandoned
            self.limits.update(doc.get("limits", {}))
            for name, t in self.tools.items():
                if t.get("risk") not in ("low", "high", "destructive"):
                    raise PolicyError(f"{name}: bad risk")
                rpm = t.get("rate_per_minute")
                if rpm is not None and (type(rpm) is not int or rpm < 1):
                    raise PolicyError(f"{name}: rate_per_minute must be a positive integer")
                for pn, ps in t.get("params", {}).items():
                    if ps.get("type") not in TYPES:
                        raise PolicyError(f"{name}.{pn}: bad type")
                    self._check_constraints(f"{name}.{pn}", ps)
            for who, pats in self.grants.items():
                if not isinstance(pats, list):
                    raise PolicyError("grants must be lists")
        except (KeyError, AttributeError, TypeError) as e:
            raise PolicyError(f"invalid manifest: {e}")

    @staticmethod
    def _check_constraints(where, ps):
        """Optional value constraints, validated at load so a typo fails closed instead of silently
        allowing everything: enum (list), pattern (regex, whole-value match, strings), min/max (numbers)."""
        ty = ps["type"]
        if "enum" in ps:
            e = ps["enum"]
            if not isinstance(e, list) or not e or not all(isinstance(v, TYPES[ty]) and not isinstance(v, bool) or ty == "boolean" and isinstance(v, bool) for v in e):
                raise PolicyError(f"{where}: enum must be a non-empty list of {ty} values")
        if "pattern" in ps:
            if ty != "string" or not isinstance(ps["pattern"], str):
                raise PolicyError(f"{where}: pattern is only valid on string params")
            try:
                re.compile(ps["pattern"])
            except re.error as e:
                raise PolicyError(f"{where}: bad pattern: {e}")
        numeric = ty in ("integer", "number")
        for k in ("min", "max"):
            if k not in ps:
                continue
            if numeric:
                if isinstance(ps[k], bool) or not isinstance(ps[k], (int, float)):
                    raise PolicyError(f"{where}: {k} must be a number")
            elif k == "min" or ty != "string" or type(ps[k]) is not int or ps[k] < 1:
                # on strings `max` is the maximum length (existing meaning); `min` is not supported
                raise PolicyError(f"{where}: {k} is only valid as a number on integer/number params")
        if numeric and "min" in ps and "max" in ps and ps["min"] > ps["max"]:
            raise PolicyError(f"{where}: min > max")

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def granted(self, agent, action):
        pats = list(self.grants.get("*", [])) + list(self.grants.get(agent, []))
        return any(fnmatch.fnmatchcase(action, p) for p in pats)

    def validate(self, spec, params):
        ps = spec.get("params", {})
        for k in params:
            if k not in ps:
                return f"unknown_param:{k}"
        for k, s in ps.items():
            if k not in params:
                if s.get("required"):
                    return f"missing_param:{k}"
                continue
            v = params[k]
            ty = TYPES[s["type"]]
            if not isinstance(v, ty) or (s["type"] in ("integer", "number") and isinstance(v, bool)):
                return f"bad_type:{k}"
            if s["type"] == "string" and len(v) > s.get("max", 4096):
                return f"too_long:{k}"
            if "enum" in s and v not in s["enum"]:
                return f"not_in_enum:{k}"
            if "pattern" in s and re.fullmatch(s["pattern"], v) is None:
                return f"pattern_mismatch:{k}"
            if s["type"] in ("integer", "number") and (("min" in s and v < s["min"]) or ("max" in s and v > s["max"])):
                return f"out_of_range:{k}"
        return None

    def decide(self, agent, action, params):
        spec = self.tools.get(action)
        if spec is None:
            return {"decision": "deny", "reason": "unknown_tool", "risk": None}
        risk = spec["risk"]
        if not self.granted(agent, action):
            return {"decision": "deny", "reason": "not_granted", "risk": risk}
        bad = self.validate(spec, params)
        if bad:
            return {"decision": "deny", "reason": bad, "risk": risk}
        if spec.get("requires_approval", risk == "destructive"):
            return {"decision": "needs_approval", "reason": "approval_required", "risk": risk}
        return {"decision": "allow", "reason": "granted", "risk": risk}
