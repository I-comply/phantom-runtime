"""Apply autofixes (non-overlapping, bottom-up, atomic writes)."""
from __future__ import annotations

import difflib
import os


def plan(findings, root):
    """Group fixable findings by file; return {rel: [(start, end, text, rule_id)]} with overlaps dropped."""
    by = {}
    for f in findings:
        if f.fix is None or f.suppressed:
            continue
        by.setdefault(f.path, []).append((f.start, f.end, f.fix, f.rule_id))
    out = {}
    for rel, items in by.items():
        items.sort(key=lambda x: (x[0], x[1]))
        kept = []
        last_end = -1
        for it in items:
            if it[0] >= last_end:
                kept.append(it)
                last_end = it[1]
        out[rel] = kept
    return out


def apply(findings, root, dry_run=False):
    """Returns (applied_count, diffs list[str])."""
    applied = 0
    diffs = []
    for rel, items in sorted(plan(findings, root).items()):
        path = os.path.join(root, rel)
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            src = fh.read()
        new = src
        for (s, e, text, _rid) in sorted(items, key=lambda x: -x[0]):
            new = new[:s] + text + new[e:]
        if new == src:
            continue
        applied += len(items)
        diffs.append("".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True), "a/" + rel, "b/" + rel)))
        if not dry_run:
            tmp = path + ".pk-tmp"
            with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
                fh.write(new)
            try:
                os.chmod(tmp, os.stat(path).st_mode)
            except OSError:
                pass
            os.replace(tmp, path)
    return applied, diffs
