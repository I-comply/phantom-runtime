import fnmatch, json
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
            self.limits = {"per_minute": 60, "approval_ttl_s": 900, "timeout_s": 10, "skew_s": 60}
            self.limits.update(doc.get("limits", {}))
            for name, t in self.tools.items():
                if t.get("risk") not in ("low", "high", "destructive"):
                    raise PolicyError(f"{name}: bad risk")
                for pn, ps in t.get("params", {}).items():
                    if ps.get("type") not in TYPES:
                        raise PolicyError(f"{name}.{pn}: bad type")
            for who, pats in self.grants.items():
                if not isinstance(pats, list):
                    raise PolicyError("grants must be lists")
        except (KeyError, AttributeError, TypeError) as e:
            raise PolicyError(f"invalid manifest: {e}")

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
