"""Static safety validator for PostgreSQL migration scripts.

Analyzes statements against live table row counts and blocks changes that
cause long ACCESS EXCLUSIVE locks or data loss. Stdlib only.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Union

DEFAULT_LOCK_ROW_THRESHOLD = 10_000

RowCounts = Union[Mapping[str, int], Callable[[str], Optional[int]]]


class Severity(enum.IntEnum):
    WARN = 1
    BLOCK = 2


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: Severity
    statement_index: int
    statement: str
    table: Optional[str]
    rows: Optional[int]
    message: str
    suggestion: str = ""


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    statements: int = 0

    @property
    def blocked(self) -> bool:
        return any(f.severity == Severity.BLOCK for f in self.findings)

    @property
    def blocking(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == Severity.BLOCK]

    def format(self) -> str:
        lines = []
        for f in self.findings:
            rows = "unknown" if f.rows is None else str(f.rows)
            lines.append(
                f"[{f.severity.name}] {f.rule} (stmt {f.statement_index}, "
                f"table={f.table}, rows={rows}): {f.message}"
                + (f" Fix: {f.suggestion}" if f.suggestion else "")
            )
        lines.append(
            f"{self.statements} statement(s), "
            f"{len(self.blocking)} blocking, "
            f"{len(self.findings) - len(self.blocking)} warning(s)."
        )
        return "\n".join(lines)


class MigrationBlocked(Exception):
    def __init__(self, report: Report):
        super().__init__(report.format())
        self.report = report


# --------------------------------------------------------------------------
# Statement splitting
# --------------------------------------------------------------------------

def _strip_and_split(sql: str) -> List[str]:
    """Split on top-level ';', dropping comments; respects quotes/$$ bodies."""
    out: List[str] = []
    buf: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        two = sql[i:i + 2]
        if two == "--":
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        if two == "/*":
            depth, i = 1, i + 2
            while i < n and depth:
                if sql[i:i + 2] == "/*":
                    depth, i = depth + 1, i + 2
                elif sql[i:i + 2] == "*/":
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            buf.append(" ")
            continue
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if sql[j + 1:j + 2] == c:
                        j += 2
                        continue
                    break
                j += 1
            buf.append(sql[i:j + 1])
            i = j + 1
            continue
        if c == "$":
            m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if m:
                tag = m.group(0)
                j = sql.find(tag, i + len(tag))
                j = n if j == -1 else j + len(tag)
                buf.append(sql[i:j])
                i = j
                continue
        if c == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def split_statements(sql: str) -> List[str]:
    return _strip_and_split(sql)


def _mask_literals(stmt: str) -> str:
    """Blank out string literals and dollar-quoted bodies for keyword matching."""
    def blank(m: "re.Match[str]") -> str:
        return "''"
    s = re.sub(r"\$([A-Za-z_]*)\$.*?\$\1\$", blank, stmt, flags=re.S)
    return re.sub(r"'(?:[^']|'')*'", blank, s)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

_IDENT = r'(?:"[^"]+"|[A-Za-z_][\w$]*)'
_QNAME = rf"{_IDENT}(?:\s*\.\s*{_IDENT})?"


def _norm(name: str) -> str:
    parts = [p.strip() for p in re.split(r'\.(?=(?:[^"]*"[^"]*")*[^"]*$)', name)]
    parts = [p[1:-1] if p.startswith('"') else p.lower() for p in parts]
    if len(parts) == 2 and parts[0] == "public":
        parts = parts[1:]
    return ".".join(parts)


class _Counts:
    def __init__(self, source: Optional[RowCounts]):
        self.source = source

    def get(self, table: Optional[str]) -> Optional[int]:
        if table is None or self.source is None:
            return None
        if callable(self.source):
            return self.source(table)
        if table in self.source:
            return int(self.source[table])
        bare = table.split(".")[-1]
        for k, v in self.source.items():
            if _norm(k) == table or _norm(k).split(".")[-1] == bare:
                return int(v)
        return None


# integer widths / varchar parsing for narrowing detection
_INT_RANK = {"smallint": 1, "int2": 1, "integer": 2, "int": 2, "int4": 2,
             "bigint": 3, "int8": 3}


def _type_info(t: str):
    t = re.sub(r"\s+", " ", t.strip().lower())
    m = re.match(r"(character varying|varchar|character|char)\s*(?:\((\d+)\))?", t)
    if m:
        kind = "varchar" if m.group(1) in ("character varying", "varchar") else "char"
        return (kind, int(m.group(2)) if m.group(2) else None)
    m = re.match(r"(smallint|integer|bigint|int2|int4|int8|int)\b", t)
    if m:
        return ("int", _INT_RANK[m.group(1)])
    if t.startswith("text"):
        return ("text", None)
    return (t.split("(")[0].strip(), None)


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

class _Ctx:
    def __init__(self, counts: _Counts, threshold: int, unknown_blocks: bool):
        self.counts = counts
        self.threshold = threshold
        self.unknown_blocks = unknown_blocks
        self.findings: List[Finding] = []
        self.created: set = set()  # tables created in this migration (empty)

    def big(self, table: Optional[str]) -> bool:
        if table in self.created:
            return False
        rows = self.counts.get(table)
        if rows is None:
            return self.unknown_blocks
        return rows >= self.threshold

    def nonempty(self, table: Optional[str]) -> bool:
        if table in self.created:
            return False
        rows = self.counts.get(table)
        if rows is None:
            return self.unknown_blocks
        return rows > 0

    def add(self, idx, stmt, rule, sev, table, msg, suggestion=""):
        self.findings.append(Finding(
            rule, sev, idx, stmt if len(stmt) < 200 else stmt[:197] + "...",
            table, self.counts.get(table), msg, suggestion))


def _check(idx: int, stmt: str, ctx: _Ctx) -> None:
    s = _mask_literals(stmt)
    flat = re.sub(r"\s+", " ", s).strip()
    low = flat.lower()

    # ---- CREATE TABLE (track as empty) ---------------------------------
    m = re.match(rf"create (?:unlogged |temp(?:orary)? )?table (?:if not exists )?({_QNAME})", low, re.I)
    if m:
        ctx.created.add(_norm(re.match(rf"create (?:unlogged |temp(?:orary)? )?table (?:if not exists )?({_QNAME})", flat, re.I).group(1)))
        return

    # ---- DROP TABLE -----------------------------------------------------
    m = re.match(rf"drop table (?:if exists )?(.+?)(?: cascade| restrict)?$", flat, re.I)
    if m:
        for raw in re.findall(_QNAME, m.group(1)):
            t = _norm(raw)
            if ctx.nonempty(t):
                ctx.add(idx, stmt, "drop-table", Severity.BLOCK, t,
                        "DROP TABLE destroys existing rows.",
                        "Back up/archive data and drop in a later, explicit migration.")
        if re.search(r"\bcascade$", low):
            ctx.add(idx, stmt, "drop-cascade", Severity.WARN, None,
                    "CASCADE drops dependent objects implicitly.")
        return

    # ---- TRUNCATE -------------------------------------------------------
    m = re.match(rf"truncate (?:table )?(?:only )?(.+?)(?: restart identity| continue identity| cascade| restrict)*$", flat, re.I)
    if m:
        for raw in re.findall(_QNAME, m.group(1)):
            t = _norm(raw)
            if ctx.nonempty(t):
                ctx.add(idx, stmt, "truncate", Severity.BLOCK, t,
                        "TRUNCATE destroys all rows.")
        return

    # ---- DELETE / UPDATE without WHERE ---------------------------------
    m = re.match(rf"(delete from|update) (?:only )?({_QNAME})", flat, re.I)
    if m and not re.search(r"\bwhere\b", low):
        t = _norm(m.group(2))
        verb = m.group(1).lower()
        if verb.startswith("delete") and ctx.nonempty(t):
            ctx.add(idx, stmt, "delete-without-where", Severity.BLOCK, t,
                    "DELETE without WHERE removes all rows.")
        elif verb == "update" and ctx.big(t):
            ctx.add(idx, stmt, "unbounded-update", Severity.BLOCK, t,
                    "UPDATE without WHERE rewrites every row; holds row locks and bloats table.",
                    "Backfill in batches outside the migration transaction.")
        return

    # ---- CREATE INDEX ---------------------------------------------------
    m = re.match(rf"create (unique )?index (concurrently )?(?:if not exists )?(?:{_IDENT} )?on (?:only )?({_QNAME})", flat, re.I)
    if m:
        t = _norm(m.group(3))
        if not m.group(2) and ctx.big(t):
            ctx.add(idx, stmt, "index-not-concurrent", Severity.BLOCK, t,
                    "CREATE INDEX without CONCURRENTLY blocks writes for the build duration.",
                    "Use CREATE INDEX CONCURRENTLY (outside a transaction).")
        return

    # ---- DROP INDEX ----------------------------------------------------
    if re.match(r"drop index (?!concurrently)", low):
        ctx.add(idx, stmt, "drop-index-not-concurrent", Severity.WARN, None,
                "DROP INDEX takes ACCESS EXCLUSIVE lock on the table.",
                "Use DROP INDEX CONCURRENTLY.")
        return

    # ---- ALTER TABLE ----------------------------------------------------
    m = re.match(rf"alter table (?:if exists )?(?:only )?({_QNAME}) (.*)$", flat, re.I)
    if m:
        table = _norm(m.group(1))
        body = m.group(2)
        for action in _split_actions(body):
            _check_alter(idx, stmt, table, action, ctx)
        return

    # ---- RENAME TABLE ---------------------------------------------------
    return


def _split_actions(body: str) -> List[str]:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p]


def _check_alter(idx, stmt, table, action, ctx: _Ctx) -> None:
    a = action.strip()
    low = a.lower()

    # DROP COLUMN
    if re.match(r"drop (?:column )?(?:if exists )?" + _IDENT, low) and not low.startswith(("drop constraint", "drop default", "drop not null", "drop identity", "drop expression")):
        if ctx.nonempty(table):
            ctx.add(idx, stmt, "drop-column", Severity.BLOCK, table,
                    "DROP COLUMN permanently deletes data and breaks running app versions.",
                    "Stop reads/writes first (expand/contract); drop in a later release.")
        return

    # RENAME
    if low.startswith("rename ") and not low.startswith("rename constraint"):
        ctx.add(idx, stmt, "rename", Severity.BLOCK if ctx.nonempty(table) else Severity.WARN,
                table, "RENAME breaks queries from running app versions.",
                "Add new column/table, dual-write, migrate, then drop old.")
        return

    # ALTER COLUMN ... TYPE
    m = re.match(rf"alter (?:column )?({_IDENT}) (?:set data )?type (.+?)(?: using .*)?$", a, re.I)
    if m:
        new_t = m.group(2).strip()
        using = bool(re.search(r"\busing\b", low))
        if ctx.nonempty(table):
            ctx.add(idx, stmt, "alter-type", Severity.BLOCK if ctx.big(table) else Severity.WARN,
                    table,
                    f"ALTER COLUMN TYPE to {new_t} "
                    + ("with USING " if using else "")
                    + "rewrites the table under ACCESS EXCLUSIVE lock and may truncate/fail on existing values.",
                    "Add a new column, backfill in batches, swap, drop old.")
        return

    # SET NOT NULL
    if re.match(rf"alter (?:column )?{_IDENT} set not null", low):
        if ctx.big(table):
            ctx.add(idx, stmt, "set-not-null", Severity.BLOCK, table,
                    "SET NOT NULL scans the whole table under ACCESS EXCLUSIVE lock.",
                    "Add CHECK (col IS NOT NULL) NOT VALID, VALIDATE it, then SET NOT NULL.")
        elif ctx.nonempty(table):
            ctx.add(idx, stmt, "set-not-null", Severity.WARN, table,
                    "SET NOT NULL fails if NULLs exist.")
        return

    # ADD COLUMN
    m = re.match(rf"add (?:column )?(?:if not exists )?({_IDENT}) (.*)$", a, re.I)
    if m and not low.startswith(("add constraint", "add primary", "add foreign", "add unique", "add check", "add exclude")):
        rest = m.group(2).lower()
        not_null = "not null" in rest
        d = re.search(r"\bdefault\b\s+(.+?)(?:\s+(?:not null|null|check|references|unique|primary|constraint|generated)\b|$)", rest)
        has_default = bool(d)
        volatile = has_default and bool(re.search(r"\b(random|clock_timestamp|uuid_generate_v\d|gen_random_uuid|nextval|timeofday)\s*\(", d.group(1)))
        if re.search(r"\b(bigserial|serial|smallserial|generated always as .* stored)\b", rest):
            volatile = True
        if not_null and not has_default and ctx.nonempty(table):
            ctx.add(idx, stmt, "add-not-null-no-default", Severity.BLOCK, table,
                    "ADD COLUMN NOT NULL without DEFAULT fails on a non-empty table.",
                    "Add nullable, backfill, then SET NOT NULL via CHECK NOT VALID.")
        elif volatile and ctx.big(table):
            ctx.add(idx, stmt, "add-column-volatile-default", Severity.BLOCK, table,
                    "Volatile DEFAULT / serial / stored generated column forces a full table rewrite under ACCESS EXCLUSIVE lock.",
                    "Add nullable column, backfill in batches, then set default.")
        if re.search(r"\breferences\b", rest) and ctx.big(table):
            ctx.add(idx, stmt, "add-fk-inline", Severity.BLOCK, table,
                    "Inline REFERENCES validates all rows while locking both tables.",
                    "Add FOREIGN KEY ... NOT VALID, then VALIDATE CONSTRAINT.")
        if re.search(r"\bunique\b|\bprimary key\b", rest) and ctx.big(table):
            ctx.add(idx, stmt, "add-unique-inline", Severity.BLOCK, table,
                    "Inline UNIQUE/PRIMARY KEY builds an index under ACCESS EXCLUSIVE lock.",
                    "CREATE UNIQUE INDEX CONCURRENTLY, then ADD CONSTRAINT ... USING INDEX.")
        return

    # ADD CONSTRAINT / ADD FOREIGN KEY / CHECK / UNIQUE / PRIMARY KEY
    if re.match(r"add (?:constraint |foreign key|check|unique|primary key|exclude)", low):
        not_valid = bool(re.search(r"\bnot valid\b", low))
        using_idx = bool(re.search(r"\busing index\b", low))
        if re.search(r"\bforeign key\b|\breferences\b", low):
            ref = re.search(rf"references ({_QNAME})", a, re.I)
            ref_t = _norm(ref.group(1)) if ref else None
            if not not_valid and (ctx.big(table) or ctx.big(ref_t)):
                ctx.add(idx, stmt, "add-fk-validating", Severity.BLOCK, table,
                        f"ADD FOREIGN KEY validates every row while locking {table} and {ref_t}.",
                        "Add with NOT VALID, then VALIDATE CONSTRAINT separately.")
            if not ctx.big(ref_t) and ref_t and not ctx.nonempty(ref_t) and ctx.nonempty(table) and not not_valid:
                ctx.add(idx, stmt, "fk-orphans", Severity.WARN, table,
                        f"Referenced table {ref_t} is empty; existing rows in {table} will violate the constraint.")
        elif re.search(r"\bcheck\b", low):
            if not not_valid and ctx.big(table):
                ctx.add(idx, stmt, "add-check-validating", Severity.BLOCK, table,
                        "ADD CHECK scans the table under ACCESS EXCLUSIVE lock.",
                        "Add with NOT VALID, then VALIDATE CONSTRAINT.")
        elif re.search(r"\bunique\b|\bprimary key\b|\bexclude\b", low):
            if not using_idx and ctx.big(table):
                ctx.add(idx, stmt, "add-unique-blocking", Severity.BLOCK, table,
                        "Adding UNIQUE/PRIMARY KEY/EXCLUDE builds an index under ACCESS EXCLUSIVE lock.",
                        "CREATE UNIQUE INDEX CONCURRENTLY, then ADD CONSTRAINT ... USING INDEX.")
        return

    # VALIDATE CONSTRAINT is the safe path; SET DEFAULT is metadata-only.
    # DROP CONSTRAINT: warn on FK/unique removal affecting integrity.
    if low.startswith("drop constraint"):
        ctx.add(idx, stmt, "drop-constraint", Severity.WARN, table,
                "Dropping a constraint removes integrity guarantees.")
        return


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def validate_sql(
    sql: str,
    row_counts: Optional[RowCounts] = None,
    lock_row_threshold: int = DEFAULT_LOCK_ROW_THRESHOLD,
    unknown_table_blocks: bool = True,
) -> Report:
    """Analyze `sql`. `row_counts` maps table name -> live row count (or a
    callable). Tables with unknown counts are treated as large when
    `unknown_table_blocks` is true (fail closed)."""
    ctx = _Ctx(_Counts(row_counts), lock_row_threshold, unknown_table_blocks)
    stmts = split_statements(sql)
    for i, stmt in enumerate(stmts, 1):
        _check(i, stmt, ctx)
    return Report(findings=ctx.findings, statements=len(stmts))


def validate_file(path: str, **kwargs) -> Report:
    with open(path, encoding="utf-8") as fh:
        return validate_sql(fh.read(), **kwargs)


def guarded_execute(
    sql: str,
    execute: Callable[[str], None],
    row_counts: Optional[RowCounts] = None,
    **kwargs,
) -> Report:
    """Validate, then call `execute(sql)` only if nothing blocks."""
    report = validate_sql(sql, row_counts, **kwargs)
    if report.blocked:
        raise MigrationBlocked(report)
    execute(sql)
    return report
