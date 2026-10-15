"""Structural, token-based pattern matching with metavariables and ellipsis.

Patterns look like target code: `$X` binds an expression, `$...ARGS` binds a
sequence, `...` matches any sequence, `<... p ...>` matches p anywhere inside.
Matching is language-aware only at the token level (strings, comments, brackets,
indentation blocks for Python), which keeps it dependency-free and fast.
"""
from __future__ import annotations

import re

from . import lang as L
from .lang import ID, NUM, STR, OP, PUNCT, META, METAELL, ELL

OPEN = {"(": ")", "[": "]", "{": "}"}
CLOSE = {")", "]", "}"}
MEMBER = {".", "?.", "::", "->"}
CONT_LEAD = {".", "?.", "&&", "||", "??", "?", ":", "+", "*", "/", "%", "==", "===", "!=", "!==", "<", ">", "<=", ">=",
             "|", "&", "^", "in", "is", "and", "or", "instanceof", "=>", "->", "=", "+=", "-=", "*=", "/=", "<<", ">>"}
UNARY_OK = {"-", "+", "!", "~", "*", "&", "++", "--", "...", "@", "\\"}
STOP_PUNCT = {",", ";"}


_KW_BEFORE_PAREN = {"return", "await", "yield", "throw", "typeof", "new", "in", "of", "else", "case", "do", "void", "delete",
                    "if", "while", "for", "switch", "with", "lambda", "not", "and", "or", "print", "assert", "elif", "raise", "is"}


class MatchBudget(Exception):
    pass


class Binding:
    __slots__ = ("key", "text", "s", "e")

    def __init__(self, key, text, s, e):
        self.key = key
        self.text = text
        self.s = s
        self.e = e

    def __repr__(self):
        return "Binding(%r)" % self.text


class Match:
    __slots__ = ("s", "e", "ts", "te", "env")

    def __init__(self, s, e, ts, te, env):
        self.s = s
        self.e = e
        self.ts = ts
        self.te = te
        self.env = env

    def __repr__(self):
        return "Match(%d,%d,%r)" % (self.s, self.e, {k: v.text for k, v in self.env.items()})


class FileCtx:
    """Tokenized source with bracket pairing; shared by all rules for one file."""

    def __init__(self, src, language, budget=400000):
        self.src = src
        self.lang = language
        self.toks = L.tokenize(src, language)
        self.pair = self._pair(self.toks)
        self.budget = budget
        self.steps = 0
        self.ids = None
        self._line_starts = None

    @staticmethod
    def _pair(toks):
        pair = {}
        stack = []
        for i, t in enumerate(toks):
            if t.kind == PUNCT:
                if t.text in OPEN:
                    stack.append((t.text, i))
                elif t.text in CLOSE:
                    for k in range(len(stack) - 1, -1, -1):
                        if OPEN[stack[k][0]] == t.text:
                            pair[stack[k][1]] = i
                            del stack[k:]
                            break
        return pair

    def token_texts(self):
        if self.ids is None:
            s = set()
            for t in self.toks:
                s.add(t.val if t.kind == STR else t.text)
            self.ids = s
        return self.ids

    def line_starts(self):
        if self._line_starts is None:
            ls = [0]
            src = self.src
            i = src.find("\n")
            while i >= 0:
                ls.append(i + 1)
                i = src.find("\n", i + 1)
            self._line_starts = ls
        return self._line_starts

    def pos(self, off):
        """1-based (line, col) for a char offset."""
        import bisect
        ls = self.line_starts()
        k = bisect.bisect_right(ls, off) - 1
        return k + 1, off - ls[k] + 1


# ---- pattern compilation -------------------------------------------------
class PItem:
    __slots__ = ("kind", "tok", "name", "items", "open", "close", "rx")

    def __init__(self, kind, tok=None, name=None, items=None, open=None, close=None):
        self.kind = kind
        self.tok = tok
        self.name = name
        self.items = items
        self.open = open
        self.close = close
        self.rx = None


_CACHE = {}


def compile_pattern(src, language):
    key = (src, language)
    p = _CACHE.get(key)
    if p is None:
        toks = L.tokenize(src, language, pattern=True)
        if not toks:
            raise ValueError("empty pattern")
        pair = FileCtx._pair(toks)
        items, _ = _build(toks, 0, len(toks), pair)
        # strip deep-ellipsis wrappers: <... p ...>
        while len(items) > 1 and items[0].kind == "ell":
            items = items[1:]
        while len(items) > 1 and items[-1].kind == "ell" and not _is_block_ell(items):
            items = items[:-1]
        p = Pattern(items, src, language)
        if len(_CACHE) > 4000:
            _CACHE.clear()
        _CACHE[key] = p
    return p


def _is_block_ell(items):
    return len(items) >= 2 and items[-1].kind == "ell" and items[-2].kind == "tok" and items[-2].tok.text == ":"


def _build(toks, i, end, pair):
    items = []
    while i < end:
        t = toks[i]
        if t.kind == PUNCT and t.text in OPEN and i in pair and pair[i] < end:
            c = pair[i]
            inner, _ = _build(toks, i + 1, c, pair)
            items.append(PItem("group", tok=t, items=_norm_commas(inner), open=t.text, close=toks[c].text))
            i = c + 1
            continue
        if t.kind == META:
            items.append(PItem("meta", tok=t, name=t.text))
        elif t.kind == METAELL:
            items.append(PItem("metaell", tok=t, name="$" + t.text[4:]))
        elif t.kind == ELL:
            items.append(PItem("ell", tok=t))
        elif t.kind == STR:
            it = PItem("tok", tok=t)
            it.rx = _string_rx(t)
            items.append(it)
        else:
            items.append(PItem("tok", tok=t))
        i += 1
    return items, i


def _is_comma(x):
    return x.kind == "tok" and x.tok.kind == PUNCT and x.tok.text == ","


def _norm_commas(items):
    """Make `, ...` / `..., ` / `, ..., ` absorb the adjacent comma (zero-arg friendly)."""
    out = []
    n = len(items)
    i = 0
    while i < n:
        it = items[i]
        if it.kind == "ell":
            if out and _is_comma(out[-1]) and i == n - 1:
                out.pop()
                out.append(PItem("ell_tail"))
                i += 1
                continue
            if i + 1 < n and _is_comma(items[i + 1]):
                out.append(PItem("ell_lead"))
                i += 2
                continue
        out.append(it)
        i += 1
    return out


_META_IN_STR = re.compile(r"\$\.\.\.[A-Z_][A-Z0-9_]*|\$[A-Z_][A-Z0-9_]*|\.\.\.")


def _string_rx(t):
    """Compile a pattern string literal into a regex when it has ... or $VARS."""
    v = t.val
    if t.text.startswith("/") and t.kind == STR and not t.text[0] in "\"'`":
        return ("regexlit", t.text)
    if not _META_IN_STR.search(v):
        return None
    parts = []
    names = {}
    pos = 0
    for m in _META_IN_STR.finditer(v):
        parts.append(re.escape(v[pos:m.start()]))
        tok = m.group()
        if tok == "...":
            parts.append(".*?")
        else:
            name = tok.lstrip("$.")
            if name in names or name == "_":
                parts.append(".*?")
            else:
                names[name] = "$" + name
                parts.append("(?P<%s>.*?)" % name)
        pos = m.end()
    parts.append(re.escape(v[pos:]))
    only_ell = v == "..."
    return (re.compile("".join(parts), re.S), only_ell)


class Pattern:
    def __init__(self, items, src, language):
        self.items = items
        self.src = src
        self.lang = language
        self.first_lit = None
        if items and items[0].kind == "tok" and items[0].tok.kind in (ID, PUNCT, OP, NUM):
            self.first_lit = items[0].tok.text
        self.required = _required(items)


def _required(items):
    out = set()
    for it in items:
        if it.kind == "tok":
            t = it.tok
            if t.kind == ID:
                out.add(t.text)
            elif t.kind == STR and it.rx is None:
                out.add(t.val)
        elif it.kind == "group":
            out |= _required(it.items)
    return out


# ---- matching ------------------------------------------------------------
def _norm_key(toks, a, b):
    return tuple((t.val if t.kind == STR else t.text) for t in toks[a:b])


class Matcher:
    def __init__(self, ctx):
        self.ctx = ctx
        self.T = ctx.toks
        self.pair = ctx.pair
        self.n = len(self.T)
        self.py = ctx.lang == "python"

    def _tick(self):
        c = self.ctx
        c.steps += 1
        if c.steps > c.budget:
            raise MatchBudget()

    # advance by one unit (token or bracket group)
    def _unit_end(self, ti, lim):
        t = self.T[ti]
        if t.kind == PUNCT and t.text in OPEN:
            c = self.pair.get(ti)
            if c is not None and c < lim:
                return c + 1
        return ti + 1

    def find_all(self, pattern):
        T = self.T
        out = []
        items = pattern.items
        first = pattern.first_lit
        last_var = items[-1].kind in ("meta", "metaell")
        lead_var = items[0].kind in ("meta", "metaell")
        seen = set()
        for ti in range(self.n):
            t = T[ti]
            if first is not None and t.text != first:
                continue
            if t.kind == PUNCT and t.text in CLOSE:
                continue
            if ti > 0:
                pv = T[ti - 1]
                if pv.kind in (OP, PUNCT) and pv.text in MEMBER and not (first in MEMBER):
                    continue
                if t.kind == PUNCT and t.text in ("(", "[") and not t.nl and (
                        pv.kind in (NUM, STR) or (pv.kind == PUNCT and pv.text in (")", "]")) or
                        (pv.kind == ID and pv.text not in _KW_BEFORE_PAREN)):
                    continue
            for end, env in self._seq(items, 0, ti, self.n, {}):
                if last_var and not self._end_boundary(end, items[-1]):
                    continue
                if end <= ti and not (items and all(i.kind in ("ell", "metaell") for i in items)):
                    continue
                key = (ti, end)
                if key in seen:
                    break
                seen.add(key)
                s = T[ti].s
                e = T[end - 1].e if end > ti else T[ti].s
                out.append(Match(s, e, ti, end, env))
                break
        return out

    def _end_boundary(self, end, last_item):
        T = self.T
        if end >= self.n:
            return True
        nt = T[end]
        if nt.kind == PUNCT and (nt.text in STOP_PUNCT or nt.text in CLOSE):
            return True
        if nt.kind == OP and nt.text in (":", "=>") and False:
            return True
        if nt.nl and not (nt.kind in (OP, ID) and nt.text in CONT_LEAD):
            prev = T[end - 1]
            if prev.kind == OP and prev.text not in ("++", "--"):
                return False
            return True
        if self.py and nt.kind == OP and nt.text == ":":
            return True
        if nt.kind == ID and nt.text in ("if", "else", "for", "while", "as", "from", "import", "then", "do") and self.py:
            return True
        return False

    def _can_extend(self, a, b):
        """May a metavariable span covering through token a-1 absorb token a?"""
        T = self.T
        t = T[a]
        if t.kind == PUNCT:
            if t.text in STOP_PUNCT or t.text in CLOSE:
                return False
            return True
        if t.nl:
            prev = T[a - 1]
            if prev.kind == OP and prev.text not in ("++", "--", ")", "]"):
                return True
            if t.kind in (OP, ID) and t.text in CONT_LEAD:
                return True
            return False
        if self.py and t.kind == OP and t.text == ":":
            return False
        if t.kind == ID and t.text in ("if", "else", "for", "as", "from", "import", "in") and self.py and False:
            return False
        if t.kind == OP and t.text in ("=>",) and False:
            return False
        return True

    def _tok_eq(self, it, t, env):
        p = it.tok
        if p.kind == STR:
            if t.kind != STR:
                return None
            rx = it.rx
            if rx is None:
                return env if p.val == t.val else None
            if isinstance(rx[0], str):  # regex literal in pattern: compare raw
                return env if p.text == t.text else None
            regex, only_ell = rx
            fstr = t.text[:3].lower().lstrip("rbu").startswith("f") if t.text[:1] not in "\"'`" else False
            if only_ell:
                if fstr and "{" in t.val:
                    return None
                if t.text[:1] == "`" and "${" in t.val:
                    return None
                return env
            m = regex.fullmatch(t.val)
            if not m:
                return None
            if m.groupdict():
                env = dict(env)
                for name, val in m.groupdict().items():
                    key = "$" + name
                    s_off = t.s + t.voff + m.start(name)
                    b = Binding((val,), val, s_off, s_off + len(val))
                    old = env.get(key)
                    if old is not None and old.key != b.key:
                        return None
                    env[key] = b
            return env
        if p.text == t.text and t.kind != STR:
            return env
        return None

    def _seq(self, items, k, ti, lim, env):
        self._tick()
        if k == len(items):
            yield ti, env
            return
        it = items[k]
        kind = it.kind
        T = self.T
        if kind == "tok":
            if ti < lim:
                e2 = self._tok_eq(it, T[ti], env)
                if e2 is not None:
                    for r in self._seq(items, k + 1, ti + 1, lim, e2):
                        yield r
            return
        if kind == "group":
            if ti < lim:
                t = T[ti]
                if t.kind == PUNCT and t.text == it.open:
                    c = self.pair.get(ti)
                    if c is not None and c < lim:
                        for e_in, env2 in self._seq(it.items, 0, ti + 1, c, env):
                            ok = e_in == c or (e_in == c - 1 and T[e_in].kind == PUNCT and T[e_in].text == ",")
                            if ok:
                                for r in self._seq(items, k + 1, c + 1, lim, env2):
                                    yield r
            return
        if kind == "ell":
            if self.py and k == len(items) - 1 and k > 0 and items[k - 1].kind == "tok" and items[k - 1].tok.text == ":" and ti > 0:
                # trailing block ellipsis: consume the indented block (and same-line suite)
                hdr = T[ti - 1].indent if T[ti - 1].nl is not None else 0
                j = ti
                while j < lim and (not T[j].nl or T[j].indent > hdr):
                    j += 1
                yield j, env
                return
            j = ti
            while True:
                for r in self._seq(items, k + 1, j, lim, env):
                    yield r
                if j >= lim:
                    return
                j = self._unit_end(j, lim)
        if kind == "ell_lead":
            for r in self._seq(items, k + 1, ti, lim, env):
                yield r
            j = ti
            while j < lim:
                j = self._unit_end(j, lim)
                if T[j - 1].kind == PUNCT and T[j - 1].text == ",":
                    for r in self._seq(items, k + 1, j, lim, env):
                        yield r
            return
        if kind == "ell_tail":
            for r in self._seq(items, k + 1, ti, lim, env):
                yield r
            if ti < lim and T[ti].kind == PUNCT and T[ti].text == ",":
                j = ti + 1
                while True:
                    for r in self._seq(items, k + 1, j, lim, env):
                        yield r
                    if j >= lim:
                        return
                    j = self._unit_end(j, lim)
            return
        if kind == "metaell":
            name = it.name
            j = ti
            while True:
                b = Binding(_norm_key(T, ti, j), self.ctx.src[T[ti].s:T[j - 1].e] if j > ti else "", T[ti].s if ti < self.n else 0,
                            T[j - 1].e if j > ti else (T[ti].s if ti < self.n else 0))
                old = env.get(name)
                if old is None or old.key == b.key:
                    env2 = env if name == "$...__" else dict(env, **{name: b})
                    for r in self._seq(items, k + 1, j, lim, env2):
                        yield r
                if j >= lim:
                    return
                j = self._unit_end(j, lim)
        if kind == "meta":
            if ti >= lim:
                return
            t0 = T[ti]
            if t0.kind == PUNCT and (t0.text in STOP_PUNCT or t0.text in CLOSE):
                return
            if t0.kind == OP and t0.text not in UNARY_OK:
                return
            name = it.name
            old = env.get(name)
            j = self._unit_end(ti, lim)
            while True:
                key = _norm_key(T, ti, j)
                if old is None or old.key == key:
                    if name == "$_":
                        env2 = env
                    else:
                        env2 = dict(env)
                        env2[name] = Binding(key, self.ctx.src[T[ti].s:T[j - 1].e], T[ti].s, T[j - 1].e)
                    for r in self._seq(items, k + 1, j, lim, env2):
                        yield r
                if j >= lim or not self._can_extend(j, lim):
                    return
                j = self._unit_end(j, lim)
