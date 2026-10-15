"""Rule model, loading and validation."""
from __future__ import annotations

import fnmatch
import os
import re

from . import lang as L
from . import yamlite
from . import matcher as M

SEVERITIES = {"INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
SEV_ALIAS = {"LOW": "INFO", "MEDIUM": "WARNING", "HIGH": "ERROR", "INVENTORY": "INFO", "EXPERIMENT": "INFO",
             "NOTE": "INFO", "WARN": "WARNING"}
POSITIVE = ("pattern", "pattern-regex", "pattern-either", "patterns")
FILTERS = ("pattern-not", "pattern-inside", "pattern-not-inside", "pattern-not-regex", "metavariable-regex",
           "metavariable-comparison", "metavariable-pattern", "metavariable-analysis", "focus-metavariable")
TOP_KEYS = {"id", "message", "severity", "languages", "metadata", "fix", "fix-regex", "paths", "options", "mode",
            "min-version", "max-version", "target", "pattern-sources", "pattern-sinks", "pattern-sanitizers",
            "pattern-propagators", "r2c-internal-project-depends-on", "interfile", "category", "description",
            "references", "technology", "confidence", "likelihood", "impact", "subcategory", "cwe", "owasp"} | set(POSITIVE) | set(FILTERS)
UNSUPPORTED = {"pattern-where-python": "arbitrary code execution is not supported", "join": "join mode is not supported"}


class RuleError(ValueError):
    pass


def sev_rank(s):
    return SEVERITIES.get(str(s).upper(), 0)


def norm_severity(s):
    s = str(s).upper()
    s = SEV_ALIAS.get(s, s)
    if s not in SEVERITIES:
        raise RuleError("invalid severity %r" % s)
    return s


class Rule:
    __slots__ = ("id", "message", "severity", "languages", "spec", "metadata", "fix", "fix_regex", "paths", "mode",
                 "options", "source", "alts", "taint")

    def __init__(self):
        self.alts = None

    def applies_to_path(self, rel):
        p = self.paths
        if not p:
            return True
        inc = p.get("include") or []
        exc = p.get("exclude") or []
        if inc and not any(path_glob(rel, g) for g in inc):
            return False
        if any(path_glob(rel, g) for g in exc):
            return False
        return True

    def to_dict(self):
        return {"id": self.id, "severity": self.severity, "languages": self.languages, "message": self.message,
                "metadata": self.metadata, "source": self.source}


def path_glob(rel, pat):
    rel = rel.replace(os.sep, "/")
    pat = pat.strip()
    if pat.startswith("/"):
        pat = pat[1:]
        return _glob_rx(pat).match(rel) is not None
    # unanchored: match against any path suffix / any component sequence
    rx = _glob_rx(pat)
    if "/" not in pat.rstrip("/"):
        parts = rel.split("/")
        return any(rx.match(x) for x in parts) or rx.match(rel) is not None
    return rx.match(rel) is not None or any(rx.match("/".join(rel.split("/")[i:])) for i in range(1, rel.count("/") + 1))


_GLOB_CACHE = {}


def _glob_rx(pat):
    rx = _GLOB_CACHE.get(pat)
    if rx is None:
        out = []
        i = 0
        p = pat.rstrip("/")
        dir_only = pat.endswith("/")
        while i < len(p):
            c = p[i]
            if c == "*":
                if p[i:i + 2] == "**":
                    i += 2
                    if p[i:i + 1] == "/":
                        out.append("(?:.*/)?")
                        i += 1
                    else:
                        out.append(".*")
                    continue
                out.append("[^/]*")
            elif c == "?":
                out.append("[^/]")
            elif c == "[":
                j = p.find("]", i + 1)
                if j < 0:
                    out.append("\\[")
                else:
                    out.append("[" + p[i + 1:j].replace("\\", "\\\\") + "]")
                    i = j
            else:
                out.append(re.escape(c))
            i += 1
        rx = re.compile("(?:" + "".join(out) + ")" + ("(?:/.*)?" if True else "") + r"\Z", re.S)
        _GLOB_CACHE[pat] = rx
    return rx


def pcre_to_py(rx):
    """Translate the PCRE bits Semgrep rules commonly use to Python `re` syntax."""
    rx = re.sub(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", rx)
    rx = re.sub(r"\\k<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P=\1)", rx)
    rx = rx.replace("\\h", "[ \\t]").replace("\\Z", "\\Z").replace("\\z", "\\Z")
    rx = re.sub(r"\(\?\^\)", "", rx)
    # possessive quantifiers / atomic groups -> plain (Python 3.11+ supports them natively)
    return rx


def compile_regex(rx, flags=re.M):
    try:
        return re.compile(pcre_to_py(rx), flags)
    except re.error as ex:
        raise RuleError("invalid regex %r: %s" % (rx, ex))


def _as_list(v):
    return v if isinstance(v, list) else [v]


def load_file(path):
    try:
        data = yamlite.load_file(path)
    except (yamlite.YamlError, ValueError) as ex:
        raise RuleError("%s: %s" % (path, ex))
    except OSError as ex:
        raise RuleError("%s: %s" % (path, ex))
    if data is None:
        return []
    if isinstance(data, dict) and "rules" in data:
        items = data["rules"]
    elif isinstance(data, list):
        items = data
    else:
        raise RuleError("%s: expected top-level 'rules:' list" % path)
    if not isinstance(items, list):
        raise RuleError("%s: 'rules' must be a list" % path)
    out = []
    for n, raw in enumerate(items):
        try:
            out.append(build_rule(raw, path))
        except RuleError as ex:
            rid = raw.get("id") if isinstance(raw, dict) else "#%d" % n
            raise RuleError("%s: rule %s: %s" % (path, rid, ex))
    return out


def build_rule(raw, source="<memory>"):
    if not isinstance(raw, dict):
        raise RuleError("rule must be a mapping")
    for k in raw:
        if k in UNSUPPORTED:
            raise RuleError("%s is unsupported (%s)" % (k, UNSUPPORTED[k]))
        if k not in TOP_KEYS:
            raise RuleError("unknown key %r" % k)
    r = Rule()
    rid = raw.get("id")
    if not isinstance(rid, str) or not re.match(r"^[A-Za-z0-9_.\-/]+$", rid):
        raise RuleError("missing or invalid 'id'")
    r.id = rid
    msg = raw.get("message")
    if not isinstance(msg, str) or not msg.strip():
        raise RuleError("missing 'message'")
    r.message = msg.strip()
    r.severity = norm_severity(raw.get("severity", ""))
    langs = raw.get("languages")
    if not isinstance(langs, list) or not langs:
        raise RuleError("'languages' must be a non-empty list")
    r.languages = [L.normalize(x) for x in langs]
    r.metadata = raw.get("metadata") or {}
    if not isinstance(r.metadata, dict):
        raise RuleError("'metadata' must be a mapping")
    for k in ("category", "confidence", "likelihood", "impact", "references", "technology", "cwe", "owasp", "subcategory"):
        if k in raw and k not in r.metadata:
            r.metadata[k] = raw[k]
    r.fix = raw.get("fix")
    r.fix_regex = raw.get("fix-regex")
    if r.fix_regex is not None:
        fr = r.fix_regex
        if not isinstance(fr, dict) or "regex" not in fr or "replacement" not in fr:
            raise RuleError("'fix-regex' needs regex and replacement")
        compile_regex(fr["regex"])
    r.paths = raw.get("paths") or {}
    r.options = raw.get("options") or {}
    r.mode = raw.get("mode", "search")
    r.source = source
    r.taint = None
    if r.mode == "taint":
        for k in ("pattern-sources", "pattern-sinks"):
            if not isinstance(raw.get(k), list) or not raw[k]:
                raise RuleError("taint mode requires non-empty %s" % k)
        r.taint = {
            "sources": raw["pattern-sources"],
            "sinks": raw["pattern-sinks"],
            "sanitizers": raw.get("pattern-sanitizers") or [],
            "propagators": raw.get("pattern-propagators") or [],
        }
        r.spec = None
        for part in ("sources", "sinks", "sanitizers"):
            for node in r.taint[part]:
                _validate_node(node, r.languages, top=True)
    elif r.mode == "search":
        ops = [k for k in POSITIVE if k in raw]
        if len(ops) != 1:
            raise RuleError("exactly one of %s is required" % ", ".join(POSITIVE))
        r.spec = {ops[0]: raw[ops[0]]}
        _validate_node(r.spec, r.languages, top=True)
    else:
        raise RuleError("unsupported mode %r" % r.mode)
    if r.fix is not None and not isinstance(r.fix, str):
        raise RuleError("'fix' must be a string")
    return r


def _validate_node(node, languages, top=False):
    if isinstance(node, str):
        node = {"pattern": node}
    if not isinstance(node, dict) or not node:
        raise RuleError("pattern clause must be a mapping")
    for k, v in node.items():
        if k in UNSUPPORTED:
            raise RuleError("%s is unsupported" % k)
        if k == "pattern" or k in ("pattern-not", "pattern-inside", "pattern-not-inside"):
            if isinstance(v, dict):
                _validate_node(v, languages)
                continue
            if not isinstance(v, str):
                raise RuleError("%s must be a string" % k)
            _check_pattern(v, languages)
        elif k in ("pattern-regex", "pattern-not-regex"):
            if not isinstance(v, str):
                raise RuleError("%s must be a string" % k)
            compile_regex(v)
        elif k == "pattern-either":
            if not isinstance(v, list) or not v:
                raise RuleError("pattern-either must be a non-empty list")
            for c in v:
                _validate_node(c, languages)
        elif k == "patterns":
            if not isinstance(v, list) or not v:
                raise RuleError("patterns must be a non-empty list")
            if not any(any(p in (c if isinstance(c, dict) else {}) for p in POSITIVE) for c in v):
                raise RuleError("patterns needs at least one positive clause (pattern/pattern-either/pattern-regex/patterns)")
            for c in v:
                _validate_node(c, languages)
        elif k == "metavariable-regex":
            if not isinstance(v, dict) or "metavariable" not in v or "regex" not in v:
                raise RuleError("metavariable-regex needs metavariable and regex")
            compile_regex(v["regex"])
        elif k == "metavariable-comparison":
            if not isinstance(v, dict) or "metavariable" not in v or "comparison" not in v:
                raise RuleError("metavariable-comparison needs metavariable and comparison")
            from .engine import compile_comparison
            compile_comparison(v["comparison"])
        elif k == "metavariable-pattern":
            if not isinstance(v, dict) or "metavariable" not in v:
                raise RuleError("metavariable-pattern needs metavariable")
            sub = {x: y for x, y in v.items() if x in POSITIVE}
            if sub:
                _validate_node(sub, [v["language"]] if v.get("language") else languages)
        elif k == "metavariable-analysis":
            if not isinstance(v, dict) or v.get("analyzer") not in ("entropy", "redos"):
                raise RuleError("metavariable-analysis analyzer must be entropy or redos")
        elif k == "focus-metavariable":
            for m in _as_list(v):
                if not isinstance(m, str) or not m.startswith("$"):
                    raise RuleError("focus-metavariable must name a $METAVAR")
        elif k in ("metadata", "exact", "by-side-effect", "requires", "label", "replace", "unsafe", "id", "message"):
            continue
        elif k in TOP_KEYS:
            continue
        else:
            raise RuleError("unknown pattern operator %r" % k)


def _check_pattern(p, languages):
    for l in languages:
        l = L.normalize(l)
        if l in ("generic",):
            lg = "generic"
        else:
            lg = l
        try:
            M.compile_pattern(p, lg)
        except ValueError as ex:
            raise RuleError("bad pattern %r: %s" % (p, ex))


def load_paths(paths):
    """Load rules from files and directories (recursively, *.yml/*.yaml/*.json)."""
    rules = []
    seen = {}
    for p in paths:
        files = []
        if os.path.isdir(p):
            for root, dirs, fs in os.walk(p):
                dirs.sort()
                for f in sorted(fs):
                    if f.endswith((".yml", ".yaml")) and not f.endswith((".test.yml", ".test.yaml", ".fixed.yml", ".fixed.yaml")):
                        files.append(os.path.join(root, f))
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise RuleError("rule path not found: %s" % p)
        for f in files:
            for r in load_file(f):
                if r.id in seen:
                    raise RuleError("duplicate rule id %s (%s and %s)" % (r.id, seen[r.id], f))
                seen[r.id] = f
                rules.append(r)
    return rules


def bundled_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
