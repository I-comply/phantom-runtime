from __future__ import annotations

import hashlib
import re

from .models import Alert, Finding, Patch, Source


def build_patches(source: Source, f: Finding) -> list[Patch]:
    actions = f.required_actions or [f.summary]
    rules = f.affected_rules or [f"{source.id}:{f.section}"]
    cite = f"{source.jurisdiction} Code § {f.section}"
    return [
        Patch(source.id, source.jurisdiction, f.section, r, a, f.severity, f.effective_date, cite)
        for r in rules
        for a in actions
    ]


def build_alert(source: Source, f: Finding, new_sha: str, detected_at: str) -> Alert:
    key = hashlib.sha256(f"{source.id}|{f.section}|{new_sha}".encode()).hexdigest()[:32]
    return Alert(
        key, source.jurisdiction, source.url, f.severity, f.confidence, f.summary, f.section,
        [p.__dict__ for p in build_patches(source, f)], detected_at,
    )


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
