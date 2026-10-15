"""AQPD contract (Adversarial Quality Poisoning Defense) and a REFERENCE engine.

BLOCKED/SPECIFIED: the production AQPD implementation was not present in the
repository supplied to the implementer. ``AqpdEngine`` is the contract a real
AQPD adapter must satisfy. ``ReferenceAqpdEngine`` is NEW, deliberately simple,
rule-based code used only so the workflow is runnable end to end. It makes no
detection-accuracy claim and must not be presented as the real AQPD.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Protocol

from .canon import CanonError, parse_strict
from .contracts import AQPD_STATUSES

MAX_SUBJECT_BYTES = 262_144


@dataclass
class AqpdResult:
    assessment_id: str
    status: str
    policy_id: str
    policy_version: int
    engine_version: str
    reason_codes: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.status not in AQPD_STATUSES:
            raise ValueError("INVALID_AQPD_STATUS")


class AqpdEngine(Protocol):
    engine_version: str

    def assess(self, content: bytes, media_type: str, policy: dict) -> AqpdResult: ...


class ReferenceAqpdEngine:
    """Policy shape: {policy_id, version, max_bytes, reject_patterns[], warn_patterns[], require_valid_json}.

    Patterns are literal case-insensitive substrings (no regex => no ReDoS).
    """
    engine_version = "reference-aqpd-0.1"

    def assess(self, content: bytes, media_type: str, policy: dict) -> AqpdResult:
        aid = "asm-" + uuid.uuid4().hex
        pid, pver = policy["policy_id"], int(policy["version"])
        base = dict(assessment_id=aid, policy_id=pid, policy_version=pver, engine_version=self.engine_version)
        limit = min(int(policy.get("max_bytes", MAX_SUBJECT_BYTES)), MAX_SUBJECT_BYTES)
        if not isinstance(content, (bytes, bytearray)):
            return AqpdResult(status="ERROR", reason_codes=["SUBJECT_NOT_BYTES"], **base)
        if len(content) > limit:
            return AqpdResult(status="REJECT", reason_codes=["SUBJECT_TOO_LARGE"], **base)
        if media_type == "application/json" or policy.get("require_valid_json"):
            try:
                parse_strict(content, max_bytes=limit)
            except CanonError as e:
                return AqpdResult(status="REJECT", reason_codes=["MALFORMED_SUBJECT:" + e.code], **base)
        try:
            text = bytes(content).decode("utf-8")
        except UnicodeDecodeError:
            return AqpdResult(status="REJECT", reason_codes=["INVALID_UTF8"], **base)
        low = text.lower()
        hits = [p for p in policy.get("reject_patterns", []) if p.lower() in low]
        if hits:
            return AqpdResult(status="REJECT", reason_codes=["PATTERN_MATCH_REJECT"],
                              evidence_refs=["rule:reject:%d" % i for i, _ in enumerate(hits)], **base)
        warns = [p for p in policy.get("warn_patterns", []) if p.lower() in low]
        if warns:
            return AqpdResult(status="WARN", reason_codes=["PATTERN_MATCH_WARN"],
                              evidence_refs=["rule:warn:%d" % i for i, _ in enumerate(warns)], **base)
        return AqpdResult(status="ACCEPT", reason_codes=["NO_RULE_MATCHED"], evidence_refs=["rule:none"], **base)
