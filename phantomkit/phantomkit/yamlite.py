"""Minimal YAML-subset loader (stdlib only).

Supports: block mappings/sequences, flow sequences/mappings, quoted and plain
scalars, block scalars (| and > with - / + chomping), comments, multi-line
plain and double-quoted scalars. Not supported: anchors, tags, merge keys,
multi-document streams, complex keys.
"""
from __future__ import annotations

import json
import re


class YamlError(ValueError):
    pass


_INT = re.compile(r"^[-+]?(0|[1-9][0-9_]*)$")
_FLOAT = re.compile(r"^[-+]?([0-9][0-9_]*)?\.[0-9]+([eE][-+]?[0-9]+)?$|^[-+]?[0-9]+[eE][-+]?[0-9]+$")


def loads(text):
    text = text.lstrip("﻿")
    s = text.lstrip()
    if s[:1] == "{" or s[:1] == "[":
        try:
            return json.loads(text)
        except ValueError:
            pass
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    p = _Parser(lines)
    return p.document()


def load_file(path):
    with open(path, encoding="utf-8") as fh:
        return loads(fh.read())


def _strip_comment(s):
    """Remove a trailing ' #' comment outside quotes."""
    q = None
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if q:
            if q == '"' and c == "\\":
                i += 2
                continue
            if c == q:
                if q == "'" and i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                q = None
        else:
            if c in "\"'" and (i == 0 or s[i - 1] in " \t[{,:-"):
                q = c
            elif c == "#" and (i == 0 or s[i - 1] in " \t"):
                return s[:i].rstrip()
        i += 1
    return s.rstrip()


def _find_key_sep(s):
    """Index of the ':' separating key and value, or -1."""
    q = None
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if q:
            if q == '"' and c == "\\":
                i += 2
                continue
            if c == q:
                q = None
        else:
            if c in "\"'" and i == 0:
                q = c
            elif c in "[{" and i == 0:
                return -1
            elif c == ":" and (i + 1 == n or s[i + 1] in " \t"):
                return i
        i += 1
    return -1


class _Parser:
    def __init__(self, lines):
        self.lines = lines
        self.n = len(lines)

    # -- helpers
    def _indent(self, i):
        ln = self.lines[i]
        return len(ln) - len(ln.lstrip(" "))

    def _blank(self, i):
        t = self.lines[i].strip()
        return t == "" or t.startswith("#")

    def _skip(self, i):
        while i < self.n and (self._blank(i) or self.lines[i].strip() in ("---", "...")):
            if self.lines[i].strip() == "...":
                return self.n
            i += 1
        return i

    def document(self):
        i = self._skip(0)
        if i >= self.n:
            return None
        val, i = self.node(i, self._indent(i))
        i = self._skip(i)
        if i < self.n:
            raise YamlError("line %d: unexpected content" % (i + 1))
        return val

    # -- structure
    def node(self, i, ind):
        t = self.lines[i].strip()
        if t == "-" or t.startswith("- "):
            return self.seq(i, ind)
        if _find_key_sep(_strip_comment(t)) >= 0:
            return self.map(i, ind)
        return self.scalar_value(_strip_comment(t), i, ind - 1)

    def seq(self, i, ind):
        out = []
        while True:
            i = self._skip(i)
            if i >= self.n or self._indent(i) != ind:
                break
            t = self.lines[i].strip()
            if not (t == "-" or t.startswith("- ")):
                break
            rest = t[1:].lstrip(" ")
            if rest == "" or rest.startswith("#"):
                j = self._skip(i + 1)
                if j < self.n and self._indent(j) > ind:
                    val, i = self.node(j, self._indent(j))
                else:
                    val, i = None, i + 1
                out.append(val)
                continue
            offset = len(self.lines[i]) - len(self.lines[i].lstrip(" ")) + (len(t) - len(rest))
            rc = _strip_comment(rest)
            if rc.startswith("- ") or rc == "-" or _find_key_sep(rc) >= 0:
                self.lines[i] = " " * offset + rest
                val, i = self.node(i, offset)
            else:
                val, i = self.scalar_value(rc, i, ind)
            out.append(val)
        return out, i

    def map(self, i, ind):
        out = {}
        while True:
            i = self._skip(i)
            if i >= self.n or self._indent(i) != ind:
                break
            t = _strip_comment(self.lines[i].strip())
            if t.startswith("- ") or t == "-":
                break
            k = _find_key_sep(t)
            if k < 0:
                raise YamlError("line %d: expected 'key: value'" % (i + 1))
            key = self.parse_scalar(t[:k].strip())
            if not isinstance(key, str):
                key = str(key) if key is not None else "null"
            rest = t[k + 1:].strip()
            if key in out:
                raise YamlError("line %d: duplicate key %r" % (i + 1, key))
            if rest == "":
                j = self._skip(i + 1)
                if j < self.n and self._indent(j) > ind:
                    val, i = self.node(j, self._indent(j))
                elif j < self.n and self._indent(j) == ind and self.lines[j].lstrip().startswith(("- ", "-\n")) or (
                        j < self.n and self._indent(j) == ind and self.lines[j].strip() == "-"):
                    val, i = self.seq(j, ind)
                else:
                    val, i = None, i + 1
            else:
                val, i = self.scalar_value(rest, i, ind)
            out[key] = val
        return out, i

    def scalar_value(self, rest, i, ind):
        """Parse a value that starts on line i; may continue on later lines."""
        if rest[:1] in ("|", ">") and re.match(r"^[|>][-+0-9]*$", rest):
            return self.block_scalar(rest, i, ind)
        if rest[:1] == '"' and not self._dq_closed(rest):
            buf = rest
            j = i + 1
            while j < self.n:
                buf += " " + self.lines[j].strip() if self.lines[j].strip() else "\n"
                if self._dq_closed(buf):
                    return self.parse_scalar(buf), j + 1
                j += 1
            raise YamlError("line %d: unterminated quoted scalar" % (i + 1))
        if rest[:1] in ("[", "{"):
            buf = rest
            j = i + 1
            while not self._balanced(buf) and j < self.n:
                buf += " " + _strip_comment(self.lines[j].strip())
                j += 1
            return self.parse_scalar(buf), j
        # plain scalar with possible continuation lines
        buf = rest
        j = i + 1
        if rest[:1] not in ("'", '"'):
            while j < self.n and not self._blank(j) and self._indent(j) > ind:
                nxt = _strip_comment(self.lines[j].strip())
                if _find_key_sep(nxt) >= 0 and self._indent(j) <= ind + 0:
                    break
                buf += " " + nxt
                j += 1
        return self.parse_scalar(buf), j

    @staticmethod
    def _dq_closed(s):
        i = 1
        while i < len(s):
            if s[i] == "\\":
                i += 2
                continue
            if s[i] == '"':
                return True
            i += 1
        return False

    @staticmethod
    def _balanced(s):
        depth = 0
        q = None
        i = 0
        while i < len(s):
            c = s[i]
            if q:
                if q == '"' and c == "\\":
                    i += 2
                    continue
                if c == q:
                    q = None
            elif c in "\"'":
                q = c
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
            i += 1
        return depth <= 0

    def block_scalar(self, header, i, ind):
        style = header[0]
        chomp = "clip"
        if "-" in header:
            chomp = "strip"
        elif "+" in header:
            chomp = "keep"
        explicit = re.search(r"[0-9]", header)
        j = i + 1
        raw = []
        base = None
        while j < self.n:
            ln = self.lines[j]
            if ln.strip() == "":
                raw.append("")
                j += 1
                continue
            cur = len(ln) - len(ln.lstrip(" "))
            if cur <= ind:
                break
            if base is None:
                base = ind + int(explicit.group()) if explicit else cur
            if cur < base:
                break
            raw.append(ln[base:])
            j += 1
        # trailing blank lines belong to chomping
        trail = 0
        while raw and raw[-1] == "":
            raw.pop()
            trail += 1
        if style == "|":
            body = "\n".join(raw)
        else:
            parts = []
            for k, ln in enumerate(raw):
                if k == 0:
                    parts.append(ln)
                elif ln == "":
                    parts.append("\n")
                elif parts and parts[-1].endswith("\n") or ln.startswith(" ") or (k and raw[k - 1].startswith(" ")):
                    parts.append(ln if parts[-1].endswith("\n") else "\n" + ln)
                else:
                    parts.append(" " + ln)
            body = "".join(parts)
        if raw:
            if chomp == "clip":
                body += "\n"
            elif chomp == "keep":
                body += "\n" * (1 + trail)
        return body, j

    # -- scalars
    def parse_scalar(self, s):
        s = s.strip()
        if s == "":
            return None
        c = s[0]
        if c == '"':
            if not self._dq_closed(s):
                raise YamlError("unterminated string: %s" % s)
            return self._unescape_dq(s)
        if c == "'":
            end = 1
            out = []
            while end < len(s):
                if s[end] == "'":
                    if end + 1 < len(s) and s[end + 1] == "'":
                        out.append("'")
                        end += 2
                        continue
                    break
                out.append(s[end])
                end += 1
            return "".join(out)
        if c == "[":
            return self._flow(s)[0]
        if c == "{":
            return self._flow(s)[0]
        low = s.lower()
        if low in ("true", "yes_"):
            return True
        if low == "false":
            return False
        if low in ("null", "~"):
            return None
        if _INT.match(s):
            return int(s.replace("_", ""))
        if _FLOAT.match(s):
            return float(s.replace("_", ""))
        if re.match(r"^0x[0-9a-fA-F]+$", s):
            return int(s, 16)
        return s

    @staticmethod
    def _unescape_dq(s):
        out = []
        i = 1
        esc = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "0": "\0", " ": " ", "b": "\b", "f": "\f"}
        while i < len(s):
            c = s[i]
            if c == "\\" and i + 1 < len(s):
                d = s[i + 1]
                if d == "u" and i + 5 < len(s) + 0:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                if d == "x":
                    out.append(chr(int(s[i + 2:i + 4], 16)))
                    i += 4
                    continue
                out.append(esc.get(d, "\\" + d))
                i += 2
                continue
            if c == '"':
                break
            out.append(c)
            i += 1
        return "".join(out)

    def _flow(self, s, i=0):
        """Parse a flow collection starting at s[i]; return (value, next_index)."""
        n = len(s)
        c = s[i]
        close = "]" if c == "[" else "}"
        i += 1
        items = []
        while True:
            while i < n and s[i] in " \t":
                i += 1
            if i >= n:
                raise YamlError("unterminated flow collection: %s" % s)
            if s[i] == close:
                i += 1
                break
            if s[i] == ",":
                i += 1
                continue
            val, i = self._flow_item(s, i, close)
            items.append(val)
        if close == "]":
            return [v if not isinstance(v, _Pair) else {v.k: v.v} for v in items], i
        out = {}
        for v in items:
            if isinstance(v, _Pair):
                out[v.k] = v.v
            else:
                out[str(v)] = None
        return out, i

    def _flow_item(self, s, i, close):
        n = len(s)
        if s[i] in "[{":
            val, i = self._flow(s, i)
            return self._maybe_pair(s, i, val)
        if s[i] in "\"'":
            q = s[i]
            j = i + 1
            while j < n:
                if q == '"' and s[j] == "\\":
                    j += 2
                    continue
                if s[j] == q:
                    if q == "'" and j + 1 < n and s[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            val = self.parse_scalar(s[i:j + 1])
            return self._maybe_pair(s, j + 1, val)
        j = i
        while j < n and s[j] not in ",]}" and not (s[j] == ":" and (j + 1 >= n or s[j + 1] in " \t,]}")):
            j += 1
        val = self.parse_scalar(s[i:j])
        return self._maybe_pair(s, j, val)

    def _maybe_pair(self, s, j, key):
        n = len(s)
        k = j
        while k < n and s[k] in " \t":
            k += 1
        if k < n and s[k] == ":":
            k += 1
            while k < n and s[k] in " \t":
                k += 1
            if k < n and s[k] not in ",]}":
                val, k = self._flow_item(s, k, "")
                if isinstance(val, _Pair):
                    val = {val.k: val.v}
            else:
                val = None
            return _Pair(key if isinstance(key, str) else str(key), val), k
        return key, j


class _Pair:
    __slots__ = ("k", "v")

    def __init__(self, k, v):
        self.k = k
        self.v = v
