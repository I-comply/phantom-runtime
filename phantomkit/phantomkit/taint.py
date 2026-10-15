"""Intra-file taint tracking over the token stream.

Sources taint expressions; assignments, loop targets and `with ... as` bindings
propagate; sanitizers cut propagation; sinks report when their region contains a
tainted expression. Scopes are function bodies; branch-local clean assignments do
not clear taint (conservative). Cross-function and cross-file flows are out of scope.
"""
from __future__ import annotations

import bisect
import re

from . import lang as L
from .lang import ID, STR, OP, PUNCT
from .matcher import Match, OPEN, CLOSE, MEMBER

ASSIGN_OPS = {"=", ":=", "+=", "-=", "*=", "/=", "%=", "|=", "&=", "^=", "||=", "&&=", "??=", "<<=", ">>=", "**=", "//="}
WEAK_OPS = ASSIGN_OPS - {"=", ":="}
CTRL = {"if", "for", "while", "switch", "catch", "synchronized", "with", "elif", "function", "foreach", "using", "lock",
        "return", "sizeof", "else", "do", "try", "await", "typeof", "in", "not", "and", "or", "assert", "except", "print",
        "new", "throw", "yield", "lambda", "match", "when", "select", "go", "defer"}
_FSTR_BRACE = re.compile(r"\{([^{}]+)\}")
_TPL_BRACE = re.compile(r"\$\{([^{}]+)\}")
_RB_BRACE = re.compile(r"#\{([^{}]+)\}")
_CHAIN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\??\.[A-Za-z_$][A-Za-z0-9_$]*)*")


class Origin:
    __slots__ = ("src", "via", "depth")

    def __init__(self, src, via, depth=0):
        self.src = src
        self.via = via
        self.depth = depth


class Analysis:
    def __init__(self, eng, ctx):
        self.eng = eng
        self.ctx = ctx
        self.T = ctx.toks
        self.n = len(self.T)
        self.py = ctx.lang == "python"
        self.pair = ctx.pair
        self._scopes()
        self._enclosing()

    # -- structure ---------------------------------------------------------
    def _enclosing(self):
        T = self.T
        self.encl = [-1] * self.n
        stack = []
        for i, t in enumerate(T):
            self.encl[i] = stack[-1] if stack else -1
            if t.kind == PUNCT and t.text in OPEN and i in self.pair:
                stack.append(i)
            elif t.kind == PUNCT and t.text in CLOSE and stack:
                # pop only on matching close
                for k in range(len(stack) - 1, -1, -1):
                    if self.pair.get(stack[k]) == i:
                        del stack[k:]
                        break
        # block depth
        self.blk = [0] * self.n
        if self.py:
            for i, t in enumerate(T):
                self.blk[i] = t.indent
        else:
            d = 0
            for i, t in enumerate(T):
                if t.kind == PUNCT and t.text == "}" and d:
                    d -= 1
                self.blk[i] = d
                if t.kind == PUNCT and t.text == "{":
                    d += 1

    def _scopes(self):
        T, n, pair = self.T, self.n, self.pair
        ranges = []
        if self.py:
            for d, t in enumerate(T):
                if t.kind == ID and t.text == "def":
                    j = d + 1
                    colon = None
                    while j < n:
                        tj = T[j]
                        if tj.kind == PUNCT and tj.text == "(" and j in pair:
                            j = pair[j] + 1
                            continue
                        if tj.kind == OP and tj.text == ":":
                            colon = j
                            break
                        if tj.nl and j > d + 1 and tj.indent <= t.indent:
                            break
                        j += 1
                    if colon is None:
                        continue
                    k = colon + 1
                    while k < n and not (T[k].nl and T[k].indent <= t.indent):
                        k += 1
                    start = d - 1 if d > 0 and T[d - 1].kind == ID and T[d - 1].text == "async" and not T[d].nl else d
                    ranges.append((start, k))
        else:
            for i, t in enumerate(T):
                body = None
                start = i
                if t.kind == ID and t.text in ("function", "func", "fn"):
                    j = i + 1
                    while j < n:
                        tj = T[j]
                        if tj.kind == PUNCT and tj.text == "{":
                            body = j
                            break
                        if tj.kind == PUNCT and tj.text in ("(", "[") and j in pair:
                            j = pair[j] + 1
                            continue
                        if tj.kind == PUNCT and tj.text == ";":
                            break
                        j += 1
                elif t.kind == OP and t.text == "=>" and i + 1 < n and T[i + 1].kind == PUNCT and T[i + 1].text == "{":
                    body = i + 1
                    if i > 0 and T[i - 1].kind == PUNCT and T[i - 1].text == ")":
                        p = None
                        for op_i, cl in pair.items():
                            if cl == i - 1:
                                p = op_i
                                break
                        start = p if p is not None else i - 1
                    else:
                        start = i - 1
                elif t.kind == PUNCT and t.text == "{" and i > 0 and T[i - 1].kind == PUNCT and T[i - 1].text == ")":
                    p = None
                    for op_i, cl in pair.items():
                        if cl == i - 1:
                            p = op_i
                            break
                    if p is not None and p > 0 and T[p - 1].kind == ID and T[p - 1].text not in CTRL and not (
                            p > 1 and T[p - 2].kind == OP and T[p - 2].text in MEMBER):
                        body = i
                        start = p - 1
                if body is not None and body in pair:
                    ranges.append((start, pair[body] + 1))
        # build nesting
        ranges = sorted(set(ranges), key=lambda r: (r[0], -r[1]))
        self.scope_range = ranges
        self.scope_parent = []
        stack = []
        for idx, (s, e) in enumerate(ranges):
            while stack and ranges[stack[-1]][1] <= s:
                stack.pop()
            self.scope_parent.append(stack[-1] if stack else -1)
            stack.append(idx)
        self.scope = [-1] * n
        for idx in sorted(range(len(ranges)), key=lambda k: -(ranges[k][1] - ranges[k][0])):
            s, e = ranges[idx]
            for t in range(s, min(e, n)):
                self.scope[t] = idx

    # -- expressions ---------------------------------------------------------
    def chain_at(self, i):
        """Return (text, end_index_exclusive) of the dotted identifier chain starting at i."""
        T = self.T
        j = i
        parts = [T[i].text]
        while j + 2 < self.n and T[j + 1].kind == OP and T[j + 1].text in (".", "?.") and T[j + 2].kind == ID:
            parts.append(T[j + 2].text)
            j += 2
        return parts, j + 1

    def stmt_end(self, i):
        """End (exclusive) of the expression starting at token i."""
        T, n = self.T, self.n
        j = i
        m = self.eng.m
        while j < n:
            t = T[j]
            if t.kind == PUNCT and (t.text in (";", ",") or t.text in CLOSE):
                break
            if j > i and not m._can_extend(j, n):
                break
            j = m._unit_end(j, n)
        return j

    def str_chains(self, tok):
        txt = tok.text
        res = []
        pre = txt[:4].lower()
        if self.py:
            if re.match(r"^[rbu]{0,2}f[rbu]{0,1}['\"]", pre):
                res = _FSTR_BRACE.findall(tok.val)
        elif tok.text.startswith("`"):
            res = _TPL_BRACE.findall(tok.val)
        elif self.ctx.lang == "ruby":
            res = _RB_BRACE.findall(tok.val)
        out = []
        for expr in res:
            out.extend(_CHAIN.findall(expr))
        return out


def run_taint(rule, eng, ctx):
    T = ctx.toks
    n = len(T)
    ev = lambda nodes: [m for node in nodes for m in eng.eval_node(node)]
    sinks = ev(rule.taint["sinks"])
    if not sinks:
        return []
    sources = ev(rule.taint["sources"])
    if not sources:
        return []
    sanit = ev(rule.taint["sanitizers"])
    A = Analysis(eng, ctx)
    san_ranges = sorted(set((m.ts, m.te) for m in sanit))
    san_starts = [r[0] for r in san_ranges]
    max_san = max((r[1] - r[0] for r in san_ranges), default=0)

    def sanitized(i):
        if not san_ranges:
            return False
        k = bisect.bisect_right(san_starts, i)
        lo = k - 1
        while lo >= 0:
            s, e = san_ranges[lo]
            if s <= i < e:
                return True
            if i - s > max_san:
                break
            lo -= 1
        return False

    src_ranges = sorted(set((m.ts, m.te, m.s, m.e) for m in sources))
    taint = {}  # (scope, text) -> Origin

    def lookup(scope, text):
        while True:
            o = taint.get((scope, text))
            if o is not None:
                return o
            if scope < 0:
                return None
            scope = A.scope_parent[scope]

    def src_info(ts, te, s, e):
        line, col = ctx.pos(s)
        return {"line": line, "col": col, "text": ctx.src[s:e][:120]}

    def expr_taint(ts, te):
        # inline source inside the expression
        for (sts, ste, ss, se) in src_ranges:
            if sts >= ts and ste <= te and ste > sts:
                if not sanitized(sts):
                    return Origin(src_info(sts, ste, ss, se), [])
            elif sts <= ts and ste >= te and te > ts:
                return Origin(src_info(sts, ste, ss, se), [])
        i = ts
        while i < te:
            t = T[i]
            if t.kind == ID and not (i > 0 and T[i - 1].kind == OP and T[i - 1].text in MEMBER):
                parts, nxt = A.chain_at(i)
                sc = A.scope[i]
                for k in range(len(parts), 0, -1):
                    key = ".".join(parts[:k])
                    o = lookup(sc, key)
                    if o is not None and not sanitized(i):
                        return Origin(o.src, _via(o.via, key), o.depth)
                i = nxt if nxt > i else i + 1
                continue
            if t.kind == STR:
                for ch in A.str_chains(t):
                    parts = ch.replace("?.", ".").split(".")
                    sc = A.scope[i]
                    for k in range(len(parts), 0, -1):
                        key = ".".join(parts[:k])
                        o = lookup(sc, key)
                        if o is not None and not sanitized(i):
                            return Origin(o.src, _via(o.via, key), o.depth)
            i += 1
        return None

    events = []
    # sources that are plain identifier chains define taint at that point (e.g. parameters)
    for (sts, ste, ss, se) in src_ranges:
        if ste > sts and T[sts].kind == ID:
            parts, nxt = A.chain_at(sts)
            if nxt == ste:
                events.append((sts, 0, "def", (".".join(parts), (sts, ste, ss, se))))
    # assignments / loop bindings
    for i, t in enumerate(T):
        if t.kind == OP and t.text in ASSIGN_OPS:
            enc = A.encl[i]
            if t.text != ":=" and enc != -1 and T[enc].text != "{":
                continue
            if t.text != ":=" and enc != -1 and T[enc].text == "{" and i + 1 < n and False:
                continue
            names = _lhs_names(A, i)
            if not names:
                continue
            re_ = A.stmt_end(i + 1)
            if re_ <= i + 1:
                continue
            events.append((i, 1, "assign", (names, i + 1, re_, t.text)))
        elif t.kind == ID and t.text in ("for", "foreach", "with", "async") and not (i > 0 and T[i - 1].kind == OP and T[i - 1].text in MEMBER):
            ev_ = _binding_event(A, i)
            if ev_:
                events.append((ev_[0], 1, "assign", ev_[1:]))
    for m in sinks:
        events.append((m.ts, 2, "sink", m))
    events.sort(key=lambda e: (e[0], e[1]))
    found = []
    seen = set()
    for idx, _, kind, payload in events:
        if kind == "def":
            text, rng = payload
            sc = A.scope[idx]
            taint[(sc, text)] = Origin(src_info(*rng), [], A.blk[idx])
        elif kind == "assign":
            names, rs, re_, op = payload
            sc = A.scope[idx] if idx < n else -1
            if sanitized(rs) and all(sanitized(k) for k in range(rs, min(re_, rs + 1))) and _wholly_sanitized(san_ranges, rs, re_):
                o = None
            else:
                o = expr_taint(rs, re_)
            for nm in names:
                key = (sc, nm)
                if o is not None:
                    taint[key] = Origin(o.src, _via(o.via, nm), A.blk[idx])
                elif op in ("=", ":=") and key in taint and A.blk[idx] <= taint[key].depth:
                    del taint[key]
        else:
            m = payload
            if m.te <= m.ts:
                continue
            o = expr_taint(m.ts, m.te)
            if o is not None:
                k = (m.s, m.e)
                if k in seen:
                    continue
                seen.add(k)
                sline, scol = ctx.pos(m.s)
                found.append((m, {"source": o.src, "via": o.via, "sink": {"line": sline, "col": scol, "text": ctx.src[m.s:m.e][:120]}}))
    return found


def _via(via, name):
    return via if via and via[-1] == name else via + [name]


def _wholly_sanitized(ranges, rs, re_):
    for (s, e) in ranges:
        if s <= rs and e >= re_:
            return True
    return False


def _lhs_names(A, op_i):
    T = A.T
    j = op_i - 1
    # walk back to statement start
    lim = max(0, op_i - 60)
    toks = []
    while j >= lim:
        t = T[j]
        toks.append(j)
        if t.nl:
            break
        if j > 0 and T[j - 1].kind == PUNCT and T[j - 1].text in (";", "{", "}") and A.encl[j] == A.encl[op_i]:
            break
        j -= 1
    toks.reverse()
    if not toks:
        return []
    # split by top-level commas
    parts = [[]]
    depth = 0
    for k in toks:
        t = T[k]
        if t.kind == PUNCT and t.text in OPEN:
            depth += 1
        elif t.kind == PUNCT and t.text in CLOSE:
            depth -= 1
        if depth == 0 and t.kind == PUNCT and t.text == ",":
            parts.append([])
            continue
        parts[-1].append(k)
    names = []
    for part in parts:
        ids = [k for k in part if T[k].kind == ID]
        if not ids:
            continue
        # python annotation: x: int = ...
        colon = [q for q, k in enumerate(part) if T[k].kind == OP and T[k].text == ":" ]
        if colon and A.py:
            part = part[:colon[0]]
        grouped = [k for k in part if T[k].kind == PUNCT and T[k].text in "([{"]
        # destructuring / tuple targets
        if grouped and T[part[0]].kind == PUNCT or (grouped and any(T[k].text in ("const", "let", "var", "val") for k in part)):
            for k in part:
                if T[k].kind == ID and T[k].text not in ("const", "let", "var", "val"):
                    names.append(T[k].text)
            continue
        # last identifier chain before any '[' subscript
        end = len(part)
        for q, k in enumerate(part):
            if T[k].kind == PUNCT and T[k].text == "[":
                end = q
                break
        part = part[:end]
        pids = [k for k in part if T[k].kind == ID]
        if not pids:
            continue
        last = pids[-1]
        # extend chain backwards
        qi = part.index(last)
        chain = [T[last].text]
        while qi >= 2 and T[part[qi - 1]].kind == OP and T[part[qi - 1]].text in (".", "?.") and T[part[qi - 2]].kind == ID:
            chain.insert(0, T[part[qi - 2]].text)
            qi -= 2
        names.append(".".join(chain))
    return [x for x in names if x not in CTRL]


def _binding_event(A, i):
    """for x in expr / for (const x of expr) / with expr as x / async for|with."""
    T, n = A.T, A.n
    if T[i].text == "async":
        return None
    kw = T[i].text
    j = i + 1
    if kw == "with":
        # python: with expr as name[, expr as name]:
        k = j
        out = None
        names = []
        spans = []
        while k < n and not (T[k].kind == OP and T[k].text == ":"):
            if T[k].kind == ID and T[k].text == "as" and k + 1 < n and T[k + 1].kind == ID:
                names.append(T[k + 1].text)
                spans.append((j, k))
                k += 2
                continue
            if T[k].kind == PUNCT and T[k].text == "(" and k in A.pair:
                k = A.pair[k] + 1
                continue
            k += 1
        if names and spans:
            return (i, names, spans[0][0], spans[0][1], "=")
        return None
    # for loops
    if j < n and T[j].kind == PUNCT and T[j].text == "(" and j in A.pair:  # js/java/c-style
        close = A.pair[j]
        k = j + 1
        names = []
        while k < close:
            if T[k].kind == ID and T[k].text in ("of", "in", ":") :
                break
            if T[k].kind == OP and T[k].text == ":":
                break
            if T[k].kind == ID and T[k].text not in ("const", "let", "var", "final", "val"):
                names.append(T[k].text)
            k += 1
        if k < close and names:
            return (i, [names[-1]], k + 1, close, "=")
        return None
    names = []
    k = j
    while k < n and not (T[k].kind == ID and T[k].text in ("in", "range")):
        if T[k].kind == OP and T[k].text == ":=":
            return None
        if T[k].kind == ID:
            names.append(T[k].text)
        if T[k].nl and k > j:
            return None
        if T[k].kind == OP and T[k].text in (":", "{"):
            return None
        k += 1
    if k >= n or not names:
        return None
    if T[k].text == "range":
        return None
    end = A.stmt_end(k + 1)
    return (i, names, k + 1, end, "=")
