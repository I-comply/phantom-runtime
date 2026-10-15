from __future__ import annotations

import difflib

from .models import SectionChange, Snapshot


def diff_snapshots(old: Snapshot, new: Snapshot) -> list[SectionChange]:
    changes: list[SectionChange] = []
    for sec in sorted(set(old.sections) | set(new.sections)):
        a, b = old.sections.get(sec), new.sections.get(sec)
        if a == b:
            continue
        kind = "added" if a is None else "removed" if b is None else "modified"
        u = "\n".join(
            difflib.unified_diff((a or "").splitlines(), (b or "").splitlines(), "before", "after", lineterm="", n=1)
        )
        changes.append(SectionChange(sec, kind, a or "", b or "", u))
    return changes
