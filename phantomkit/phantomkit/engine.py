"""Rule evaluation: pattern algebra, metavariable filters and taint tracking."""
from __future__ import annotations

import ast
import bisect
import math
import re

from . import lang as L
from . import matcher as M
from .matcher import Match, Binding
from .rules import POSITIVE, FILTERS, compile_regex, RuleError, pcre_to_py

_META_RX = re.compile(r"\$\.\.\.[A-Z_][A-Z0-9_]*|\$[A-Z_][A-Z0-9_]*")


class Finding:
    __slots__ = ("rule_id", "path", "line", "col", "end_line", "end_col", "start", "end", "message", "severity",
                 "metadata", "snippet", "fix", "fingerprint", "trace", "suppressed", "suppress_reason", "rule_source", "kind")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))
        if self.metadata is None:
            self.metadata = {}
        if self.suppressed is None:
            self.suppressed = False
        if self.kind is None:
            self.kind = "sast"


def interpolate(text, env):
    if not text or "$" not in text:
        return text

    def rep(m):
        b = env.get(m.group())
        if b is None and m.group().startswith("$..."):
            b = env.get("$" + m.group()[4:])
        return b.text if b is not None else m.group()

    return _META_RX.sub(rep, text)


# ---- comparison expressions (safe evaluator) ------------------------------
_CMP_OK = (ast.Expression, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Constant, ast.Name, ast.Load,
           ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.In, ast.NotIn, ast.Call, ast.Tuple, ast.List)
_CMP_FUNCS = {"int": int, "float": float, "str": str, "len": len, "abs": abs, "min": min, "max": max}


def compile_comparison(expr):
    e = _META_RX.sub(lambda m: "__mv_" + m.group()[1:], expr)
    try:
        tree = ast.parse(e.strip(), mode="eval")
    except SyntaxError as ex:
        raise RuleError("invalid comparison %r: %s" % (expr, ex))
    for node in ast.walk(tree):
        if not isinstance(node, _CMP_OK):
            raise RuleError("unsupported syntax in comparison %r" % expr)
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in _CMP_FUNCS):
            raise RuleError("unsupported call in comparison %r" % expr)
        if isinstance(node, ast.Name) and not (node.id.startswith("__mv_") or node.id in _CMP_FUNCS or node.id in ("True", "False")):
            raise RuleError("unknown name %r in comparison" % node.id)
    return compile(tree, "<cmp>", "eval")


def _num(text, base=None):
    t = text.strip().strip("\"'`")
    try:
        if base:
            return int(t, base)
        return int(t, 0)
    except ValueError:
        try:
            return float(t)
        except ValueError:
            return t


def entropy(s):
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum(v / n * math.log2(v / n) for v in freq.values())


def _merge(a, b):
    if not b:
        return a
    out = dict(a)
    for k, v in b.items():
        o = out.get(k)
        if o is not None and o.key != v.key:
            return None
        out[k] = v
    return out


def _contains(a, b):
    return a.s <= b.s and b.e <= a.e


def _as_list(v):
    return v if isinstance(v, list) else [v]


class Engine:
    """Evaluates rules against one tokenized file."""

    def __init__(self, ctx, path=""):
        self.ctx = ctx
        self.m = M.Matcher(ctx)
        self.path = path
        self._pat_cache = {}
        self._tok_starts = None
        self._rx_cache = {}

    # -- primitives ---------------------------------------------------
    def tok_range(self, s, e):
        if self._tok_starts is None:
            self._tok_starts = [t.s for t in self.ctx.toks]
        ts = bisect.bisect_left(self._tok_starts, s)
        te = bisect.bisect_left(self._tok_starts, e)
        return ts, te

    def mk(self, s, e, env):
        ts, te = self.tok_range(s, e)
        return Match(s, e, ts, te, env)

    def pat(self, src, language=None):
        key = (src, language or self.ctx.lang)
        r = self._pat_cache.get(key)
        if r is None:
            p = M.compile_pattern(src, language or self.ctx.lang)
            r = self.m.find_all(p)
            self._pat_cache[key] = r
        return r

    def regex(self, rx):
        c = self._rx_cache.get(rx)
        if c is None:
            c = compile_regex(rx)
            self._rx_cache[rx] = c
        out = []
        src = self.ctx.src
        for mt in c.finditer(src):
            if mt.end() == mt.start():
                continue
            env = {}
            for name, val in mt.groupdict().items():
                if val is not None:
                    env["$" + name] = Binding((val,), val, mt.start(name), mt.end(name))
            out.append(self.mk(mt.start(), mt.end(), env))
        return out

    # -- node evaluation ------------------------------------------------
    def eval_node(self, node):
        if isinstance(node, str):
            return self.pat(node)
        if "pattern" in node and not isinstance(node["pattern"], dict):
            res = self.pat(node["pattern"])
        elif "pattern" in node:
            res = self.eval_node(node["pattern"])
        elif "pattern-regex" in node:
            res = self.regex(node["pattern-regex"])
        elif "pattern-either" in node:
            res = []
            for c in node["pattern-either"]:
                res.extend(self.eval_node(c))
            res = _dedupe(res)
        elif "patterns" in node:
            res = self.eval_patterns(node["patterns"])
        else:
            raise RuleError("no positive operator in %s" % list(node))
        extra = {k: v for k, v in node.items() if k in FILTERS}
        if extra:
            res = self.apply_filters(res, list(extra.items()))
        return res

    def eval_patterns(self, clauses):
        positives = []
        filters = []
        for c in clauses:
            if isinstance(c, str):
                c = {"pattern": c}
            for k, v in c.items():
                if k in POSITIVE:
                    positives.append({k: v})
                elif k in FILTERS:
                    filters.append((k, v))
        base = None
        for node in positives:
            cur = self.eval_node(node)
            if base is None:
                base = cur
            else:
                base = _intersect(base, cur)
            if not base:
                return []
        if base is None:
            return []
        # context filters first, then the rest
        order = {"pattern-inside": 0, "pattern-not-inside": 1, "pattern-not": 2, "pattern-not-regex": 2}
        filters.sort(key=lambda kv: order.get(kv[0], 5 if kv[0] != "focus-metavariable" else 9))
        return self.apply_filters(base, filters)

    def apply_filters(self, res, filters):
        for k, v in filters:
            if not res:
                return res
            if k == "pattern-inside":
                ctxm = self.eval_node(v) if isinstance(v, dict) else self.pat(v)
                nres = []
                for m in res:
                    for c in ctxm:
                        if _contains(c, m):
                            env = _merge(m.env, c.env)
                            if env is not None:
                                nres.append(Match(m.s, m.e, m.ts, m.te, env))
                                break
                res = nres
            elif k == "pattern-not-inside":
                ctxm = self.eval_node(v) if isinstance(v, dict) else self.pat(v)
                res = [m for m in res if not any(_contains(c, m) and _merge(m.env, c.env) is not None for c in ctxm)]
            elif k == "pattern-not":
                neg = self.eval_node(v) if isinstance(v, dict) else self.pat(v)
                res = [m for m in res if not any((_contains(n, m) or _contains(m, n)) and _merge(m.env, n.env) is not None
                                                 and (n.s == m.s or n.e == m.e or _contains(n, m)) for n in neg)]
            elif k == "pattern-not-regex":
                neg = self.regex(v)
                res = [m for m in res if not any(_contains(n, m) or (n.s <= m.s < n.e) for n in neg)]
            elif k == "metavariable-regex":
                rx = self._rx_cache.get(("mv", v["regex"]))
                if rx is None:
                    rx = compile_regex(v["regex"], re.S)
                    self._rx_cache[("mv", v["regex"])] = rx
                name = v["metavariable"]
                res = [m for m in res if name in m.env and rx.match(_mv_text(m.env[name]))]
            elif k == "metavariable-comparison":
                code = self._rx_cache.get(("cmp", v["comparison"]))
                if code is None:
                    code = compile_comparison(v["comparison"])
                    self._rx_cache[("cmp", v["comparison"])] = code
                name = v["metavariable"]
                base = v.get("base")
                keep = []
                for m in res:
                    names = {"__mv_" + n[1:]: _num(b.text, base) for n, b in m.env.items() if not n.startswith("$...")}
                    names.update(_CMP_FUNCS)
                    try:
                        if name in m.env and eval(code, {"__builtins__": {}}, names):
                            keep.append(m)
                    except Exception:
                        pass
                res = keep
            elif k == "metavariable-analysis":
                name = v["metavariable"]
                an = v["analyzer"]
                keep = []
                for m in res:
                    b = m.env.get(name)
                    if b is None:
                        continue
                    text = b.text.strip("\"'`")
                    if an == "entropy":
                        if len(text) >= int(v.get("min-length", 8)) and entropy(text) >= float(v.get("threshold", 3.5)):
                            keep.append(m)
                    elif an == "redos":
                        if _redos_prone(text):
                            keep.append(m)
                res = keep
            elif k == "metavariable-pattern":
                name = v["metavariable"]
                sub = {x: y for x, y in v.items() if x in POSITIVE}
                lg = L.normalize(v["language"]) if v.get("language") else None
                keep = []
                for m in res:
                    b = m.env.get(name)
                    if b is None or not sub:
                        continue
                    if lg == "generic" or (lg is None and self.ctx.lang == "generic"):
                        text = b.text
                    else:
                        text = b.text
                    if _sub_matches(text, lg or self.ctx.lang, sub, self.path):
                        keep.append(m)
                res = keep
            elif k == "focus-metavariable":
                names = _as_list(v)
                out = []
                for m in res:
                    for n in names:
                        b = m.env.get(n)
                        if b is not None:
                            out.append(self.mk(b.s, b.e, m.env))
                            break
                res = out
        return res


def _mv_text(b):
    return b.text


def _redos_prone(rx):
    """Heuristic: nested quantifiers like (a+)+ or (a*)*."""
    return bool(re.search(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*[+*{]", rx)) or bool(re.search(r"\([^()]*\|[^()]*\)[+*]", rx) and re.search(r"\(([^()|]+)\|\1", rx))


def _sub_matches(text, language, spec, path):
    try:
        ctx = M.FileCtx(text, language, budget=50000)
        eng = Engine(ctx, path)
        return bool(eng.eval_node(spec))
    except M.MatchBudget:
        return False


def _dedupe(ms):
    seen = {}
    for m in ms:
        key = (m.s, m.e, tuple(sorted((k, v.key) for k, v in m.env.items())))
        if key not in seen:
            seen[key] = m
    return list(seen.values())


def _intersect(a, b):
    out = []
    for m in a:
        for n in b:
            if _contains(n, m) or _contains(m, n):
                env = _merge(m.env, n.env)
                if env is not None:
                    # keep the narrower range
                    r = m if (m.e - m.s) <= (n.e - n.s) else n
                    out.append(Match(r.s, r.e, r.ts, r.te, env))
                    break
    return out


# ---- rule driver ----------------------------------------------------------
def prefilter(rule):
    """Alternatives of required literal tokens; None means no cheap prefilter."""
    if rule.alts is not None:
        return rule.alts or None
    alts = _alts_for_rule(rule)
    rule.alts = alts if alts is not None else []
    return alts


def _pat_required(src, languages):
    req = None
    for l in languages:
        try:
            r = M.compile_pattern(src, l if l != "generic" else "generic").required
        except ValueError:
            return None
        req = r if req is None else (req & r)
    return req or set()


def _alts_node(node, languages):
    if isinstance(node, str):
        r = _pat_required(node, languages)
        return None if r is None else [r]
    if "pattern" in node and isinstance(node["pattern"], str):
        r = _pat_required(node["pattern"], languages)
        return None if r is None else [r]
    if "pattern-either" in node:
        out = []
        for c in node["pattern-either"]:
            a = _alts_node(c, languages)
            if a is None:
                return None
            out.extend(a)
        return out
    if "patterns" in node:
        best = None
        for c in node["patterns"]:
            if isinstance(c, dict) and any(k in c for k in ("pattern", "pattern-either", "patterns")):
                a = _alts_node(c, languages)
                if a is not None and (best is None or min(len(x) for x in a) > min(len(x) for x in best)):
                    best = a
        return best
    return None


def _alts_for_rule(rule):
    if rule.mode == "taint":
        out = []
        for node in rule.taint["sinks"]:
            a = _alts_node(node, rule.languages)
            if a is None:
                return None
            out.extend(a)
        return out
    return _alts_node(rule.spec, rule.languages)


def run_rule(rule, eng, ctx, path):
    """Return findings for one rule on one file."""
    alts = prefilter(rule)
    if alts is not None:
        texts = ctx.token_texts()
        if not any(a <= texts for a in alts):
            return []
    if rule.mode == "taint":
        from .taint import run_taint
        matches = run_taint(rule, eng, ctx)
    else:
        matches = eng.eval_node(rule.spec)
    out = []
    src = ctx.src
    for m in matches:
        trace = None
        if isinstance(m, tuple):
            m, trace = m
        line, col = ctx.pos(m.s)
        eline, ecol = ctx.pos(m.e)
        ls = ctx.line_starts()
        snippet = src[ls[line - 1]: (ls[eline] if eline < len(ls) else len(src))].rstrip("\n")
        msg = interpolate(rule.message, m.env)
        fix = None
        if rule.fix is not None:
            fix = interpolate(rule.fix, m.env)
        elif rule.fix_regex:
            fr = rule.fix_regex
            seg = src[m.s:m.e]
            try:
                rx = compile_regex(fr["regex"], re.S)
                cnt = int(fr.get("count", 0))
                fx = rx.sub(pcre_to_py_repl(fr["replacement"]), seg, count=cnt)
                fix = fx if fx != seg else None
            except re.error:
                fix = None
        out.append(Finding(rule_id=rule.id, path=path, line=line, col=col, end_line=eline, end_col=ecol, start=m.s, end=m.e,
                           message=msg, severity=rule.severity, metadata=rule.metadata, snippet=snippet, fix=fix,
                           trace=trace, rule_source=rule.source))
    return out


def pcre_to_py_repl(r):
    return re.sub(r"\$(\d+)", r"\\\1", r)
