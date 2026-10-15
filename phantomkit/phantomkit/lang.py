"""Language registry and tokenizer used by the structural matcher."""
from __future__ import annotations

import os
import re

# kind constants
ID, NUM, STR, OP, PUNCT, META, METAELL, ELL = "id", "num", "str", "op", "punct", "meta", "metaell", "ell"

EXT = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".go": "go", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".cxx": "cpp",
    ".cs": "csharp", ".php": "php", ".rb": "ruby", ".rs": "rust", ".swift": "swift",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".tf": "terraform", ".hcl": "terraform", ".tfvars": "terraform",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".toml": "generic", ".ini": "generic",
    ".cfg": "generic", ".env": "generic", ".properties": "generic", ".xml": "generic",
    ".html": "html", ".htm": "html", ".vue": "html", ".sql": "generic", ".gradle": "java",
}
BASENAME = {"dockerfile": "dockerfile", "containerfile": "dockerfile", "jenkinsfile": "java", "makefile": "generic"}

# Language families: a rule written for key also applies to value languages.
ALIASES = {
    "js": "javascript", "ts": "typescript", "py": "python", "python3": "python", "golang": "go",
    "sh": "bash", "shell": "bash", "dockerfile": "dockerfile", "docker": "dockerfile",
    "yml": "yaml", "hcl": "terraform", "regex": "generic", "none": "generic", "cs": "csharp",
}
RELATED = {
    "javascript": {"javascript", "typescript"},
    "typescript": {"typescript", "javascript"},
}

HASH_COMMENT = {"python", "ruby", "bash", "dockerfile", "yaml", "generic", "terraform", "php"}
SLASH_COMMENT = {"javascript", "typescript", "go", "java", "kotlin", "scala", "c", "cpp", "csharp",
                 "php", "rust", "swift", "terraform", "json", "html_js"}
INDENT_BLOCK = {"python"}


def normalize(name):
    n = str(name).strip().lower()
    return ALIASES.get(n, n)


def detect(path, head=""):
    base = os.path.basename(path).lower()
    if base in BASENAME:
        return BASENAME[base]
    if base.startswith("dockerfile."):
        return "dockerfile"
    ext = os.path.splitext(base)[1]
    if ext in EXT:
        return EXT[ext]
    if head.startswith("#!"):
        first = head.split("\n", 1)[0]
        for key, lang in (("python", "python"), ("node", "javascript"), ("bash", "bash"), ("sh", "bash"), ("ruby", "ruby"), ("php", "php")):
            if re.search(r"\b%s\d*\b" % key, first):
                return lang
    return None


def lang_matches(rule_langs, file_lang):
    if file_lang is None:
        return any(normalize(l) == "generic" for l in rule_langs)
    for l in rule_langs:
        l = normalize(l)
        if l == "generic":
            return True
        if l == file_lang or file_lang in RELATED.get(l, ()):
            return True
        # yaml rules also apply to json; dockerfile is its own thing
        if l == "yaml" and file_lang == "json":
            return True
    return False


class Tok:
    __slots__ = ("kind", "text", "s", "e", "line", "col", "nl", "indent", "val", "voff")

    def __init__(self, kind, text, s, e, line, col, nl, indent):
        self.kind = kind
        self.text = text
        self.s = s
        self.e = e
        self.line = line
        self.col = col
        self.nl = nl          # first token on its line
        self.indent = indent  # indentation of its line
        self.val = text
        self.voff = 0
        if kind == STR:
            self.val, self.voff = string_value2(text)

    def __repr__(self):
        return "Tok(%s,%r)" % (self.kind, self.text)


_STR_PREFIX = re.compile(r"(?:[rRbBuUfF]{1,2})(?=['\"])")


def string_value(text):
    return string_value2(text)[0]


def string_value2(text):
    t = text
    off = 0
    m = _STR_PREFIX.match(t)
    if m:
        t = t[m.end():]
        off = m.end()
    for q in ('"""', "'''"):
        if t.startswith(q) and t.endswith(q) and len(t) >= 6:
            return t[3:-3], off + 3
    if t and t[0] in "\"'`" and len(t) >= 2 and t[-1] == t[0]:
        return t[1:-1], off + 1
    return t, off


_OPS3 = {">>>=", "<<=", ">>=", ">>>", "===", "!==", "**=", "//=", "...", "&&=", "||=", "??=", "<=>", "->*", "<..", "..>"}
_OPS2 = {"==", "!=", "<=", ">=", "&&", "||", "??", "?.", "=>", "->", "::", "++", "--", "+=", "-=", "*=", "/=", "%=",
         "&=", "|=", "^=", "<<", ">>", "**", ":=", "..", "|>", "<-", "@@"}
_PUNCT = set("()[]{},;")
_IDSTART = re.compile(r"[A-Za-z_\u0080-\uffff$]")
_IDREST = re.compile(r"[A-Za-z0-9_\u0080-\uffff$]")
_NUMRE = re.compile(r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:[0-9][0-9_]*\.?[0-9_]*|\.[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)?[a-zA-Z]{0,2}")
_REGEX_PREV_OK = {"(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*", "%", "<", ">", "~", "^", "=>", "==", "===", "!=", "!==", "&&", "||", "??", "return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do", "yield", "await"}


def tokenize(src, lang, pattern=False):
    """Tokenize source for lang. In pattern mode recognise $X / $...X / ... metavariables."""
    toks = []
    n = len(src)
    i = 0
    line = 1
    line_start = 0
    nl = True
    indent = 0
    hash_c = lang in HASH_COMMENT
    slash_c = lang in SLASH_COMMENT
    c_like = slash_c
    py = lang == "python"
    js = lang in ("javascript", "typescript", "html")
    template_lit = js or lang == "go"
    dollar_id = lang in ("php", "bash")

    def emit(kind, s, e):
        nonlocal nl
        toks.append(Tok(kind, src[s:e], s, e, line, s - line_start + 1, nl, indent))
        nl = False

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            line_start = i
            nl = True
            j = i
            while j < n and src[j] in " \t":
                j += 1
            indent = j - i
            # tabs count as 8 for indent comparison purposes
            if "\t" in src[i:j]:
                indent = len(src[i:j].expandtabs(8))
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if i == 0 or (src[i - 1] == "\n" and nl):
            pass
        # comments
        if hash_c and c == "#" and not (pattern and lang in ("php",)):
            if lang == "php" and src.startswith("#[", i):
                pass
            else:
                while i < n and src[i] != "\n":
                    i += 1
                continue
        if slash_c and c == "/" and i + 1 < n:
            d = src[i + 1]
            if d == "/":
                while i < n and src[i] != "\n":
                    i += 1
                continue
            if d == "*":
                j = src.find("*/", i + 2)
                j = n if j < 0 else j + 2
                line += src.count("\n", i, j)
                k = src.rfind("\n", i, j)
                if k >= 0:
                    line_start = k + 1
                i = j
                continue
        if lang == "html" and src.startswith("<!--", i):
            j = src.find("-->", i + 4)
            j = n if j < 0 else j + 3
            line += src.count("\n", i, j)
            k = src.rfind("\n", i, j)
            if k >= 0:
                line_start = k + 1
            i = j
            continue
        # pattern metavariables / ellipsis
        if pattern:
            if src.startswith("$...", i):
                m = re.compile(r"\$\.\.\.[A-Z_][A-Z0-9_]*").match(src, i)
                if m:
                    emit(METAELL, i, m.end())
                    i = m.end()
                    continue
            if c == "$":
                m = re.compile(r"\$[A-Z_][A-Z0-9_]*").match(src, i)
                if m:
                    emit(META, i, m.end())
                    i = m.end()
                    continue
            if src.startswith("<...", i):
                emit(ELL, i, i + 4)
                i += 4
                continue
            if src.startswith("...>", i):
                emit(ELL, i, i + 4)
                i += 4
                continue
            if src.startswith("...", i):
                emit(ELL, i, i + 3)
                i += 3
                continue
        # strings
        if c in "\"'`" or (py and c in "rRbBuUfF" and _STR_PREFIX.match(src, i, min(n, i + 3))):
            j = i
            if c not in "\"'`":
                m = _STR_PREFIX.match(src, i)
                j = m.end()
            q = src[j]
            if q == "`" and not template_lit and lang not in ("bash",):
                emit(PUNCT, i, i + 1)
                i += 1
                continue
            triple = (py or lang in ("java", "kotlin", "scala", "csharp", "bash")) and src.startswith(q * 3, j) and q != "`"
            raw = "r" in src[i:j].lower() if j > i else False
            if triple:
                end = src.find(q * 3, j + 3)
                end = n if end < 0 else end + 3
            else:
                k = j + 1
                depth = 0
                while k < n:
                    ch = src[k]
                    if ch == "\\" and not (lang == "go" and q == "`") and not (raw and False):
                        k += 2
                        continue
                    if q == "`" and lang in ("javascript", "typescript", "html"):
                        if ch == "$" and k + 1 < n and src[k + 1] == "{":
                            depth += 1
                            k += 2
                            continue
                        if ch == "}" and depth:
                            depth -= 1
                            k += 1
                            continue
                        if ch == q and depth == 0:
                            k += 1
                            break
                    elif ch == q:
                        k += 1
                        break
                    elif ch == "\n" and q != "`" and not (py and False):
                        # unterminated: stop at end of line
                        break
                    k += 1
                end = min(k, n)
            seg_lines = src.count("\n", i, end)
            emit(STR, i, end)
            if seg_lines:
                line += seg_lines
                line_start = src.rfind("\n", i, end) + 1
            i = end
            continue
        # numbers
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = _NUMRE.match(src, i)
            if m and m.end() > i:
                emit(NUM, i, m.end())
                i = m.end()
                continue
        # regex literals (js)
        if js and c == "/":
            prev = toks[-1] if toks else None
            if prev is None or (prev.kind in (OP, PUNCT) and prev.text in _REGEX_PREV_OK) or (prev.kind == ID and prev.text in _REGEX_PREV_OK):
                k = i + 1
                in_cls = False
                ok = False
                while k < n and src[k] != "\n":
                    ch = src[k]
                    if ch == "\\":
                        k += 2
                        continue
                    if ch == "[":
                        in_cls = True
                    elif ch == "]":
                        in_cls = False
                    elif ch == "/" and not in_cls:
                        ok = True
                        k += 1
                        break
                    k += 1
                if ok:
                    while k < n and src[k].isalpha():
                        k += 1
                    emit(STR, i, k)
                    i = k
                    continue
        # identifiers
        if _IDSTART.match(c):
            j = i + 1
            while j < n and _IDREST.match(src[j]):
                j += 1
            if c == "$" and j == i + 1 and not dollar_id:
                emit(OP, i, i + 1)
                i += 1
                continue
            emit(ID, i, j)
            i = j
            continue
        # operators / punct
        if c in _PUNCT:
            emit(PUNCT, i, i + 1)
            i += 1
            continue
        op = None
        for ln, group in ((4, None), (3, _OPS3), (2, _OPS2)):
            seg = src[i:i + ln]
            if ln == 4:
                if seg in (">>>=",):
                    op = seg
                    break
                continue
            if seg in group:
                op = seg
                break
        if op is None:
            op = c
        if py and op in ("//", "->"):
            pass
        emit(OP, i, i + len(op))
        i += len(op)
    return toks
