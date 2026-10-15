"""CLI: python -m migration_validator.cli  (cwd: supabase/) [opts] FILE...

Row counts: --row-counts counts.json  ({"table": n}) or --dsn DSN (uses psql,
exact COUNT(*) per table referenced). Exit 1 if any migration is blocked.
With --exec CMD, runs CMD FILE for each passing migration (e.g. "psql $DSN -f").
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys

from .validator import DEFAULT_LOCK_ROW_THRESHOLD, validate_file


def _psql_counter(dsn: str):
    cache = {}

    def count(table: str):
        if table in cache:
            return cache[table]
        if not re.fullmatch(r"[A-Za-z_][\w$]*(\.[A-Za-z_][\w$]*)?", table):
            cache[table] = None
            return None
        r = subprocess.run(
            ["psql", dsn, "-X", "-A", "-t", "-c", f"SELECT count(*) FROM {table}"],
            capture_output=True, text=True)
        cache[table] = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None
        return cache[table]
    return count


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="migration-validator")
    p.add_argument("files", nargs="+")
    p.add_argument("--row-counts")
    p.add_argument("--dsn")
    p.add_argument("--threshold", type=int, default=DEFAULT_LOCK_ROW_THRESHOLD)
    p.add_argument("--allow-unknown", action="store_true",
                   help="treat tables with unknown row counts as empty")
    p.add_argument("--exec", dest="exec_cmd")
    a = p.parse_args(argv)

    counts = None
    if a.row_counts:
        with open(a.row_counts) as fh:
            counts = json.load(fh)
    elif a.dsn:
        counts = _psql_counter(a.dsn)

    rc = 0
    for f in a.files:
        rep = validate_file(f, row_counts=counts, lock_row_threshold=a.threshold,
                            unknown_table_blocks=not a.allow_unknown)
        print(f"== {f}")
        print(rep.format())
        if rep.blocked:
            rc = 1
            continue
        if a.exec_cmd:
            r = subprocess.run(shlex.split(a.exec_cmd) + [f])
            if r.returncode:
                return r.returncode
    return rc


if __name__ == "__main__":
    sys.exit(main())
