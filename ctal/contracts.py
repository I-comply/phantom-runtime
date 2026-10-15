"""Status vocabularies and the default fail-closed decision matrix.

AQPD and CLES statuses are evaluated independently; this module only maps the
two *separate* results to a workflow outcome. There is no combined score.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

AQPD_STATUSES = ("ACCEPT", "WARN", "QUARANTINE", "REJECT", "REVIEW", "UNKNOWN", "ERROR")
CLES_STATUSES = ("AUTHORIZED", "DENIED", "EXPIRED", "REVOKED", "INVALID_SIGNATURE", "UNKNOWN", "ERROR")
OUTCOMES = ("PROCEED", "BLOCK", "HOLD_FOR_REVIEW", "ERROR")
EVENT_TYPES = (
    "subject_received", "assessment_started", "assessment_completed", "policy_created",
    "policy_version_published", "license_issued", "entitlement_verified", "entitlement_denied",
    "assurance_envelope_signed", "envelope_verification_failed", "remediation_created",
    "regression_case_added", "release_manifest_signed", "export_created", "key_rotated", "key_revoked",
)

_SEVERITY = {"PROCEED": 0, "HOLD_FOR_REVIEW": 1, "BLOCK": 2, "ERROR": 3}

# AQPD side: only ACCEPT proceeds. WARN holds unless an explicit, versioned
# decision policy (warn_action == "PROCEED") says otherwise.
_AQPD_OUTCOME = {
    "ACCEPT": "PROCEED", "WARN": "HOLD_FOR_REVIEW", "REVIEW": "HOLD_FOR_REVIEW",
    "UNKNOWN": "HOLD_FOR_REVIEW", "QUARANTINE": "BLOCK", "REJECT": "BLOCK", "ERROR": "ERROR",
}
# CLES side: only AUTHORIZED proceeds.
_CLES_OUTCOME = {
    "AUTHORIZED": "PROCEED", "DENIED": "BLOCK", "EXPIRED": "BLOCK", "REVOKED": "BLOCK",
    "INVALID_SIGNATURE": "BLOCK", "UNKNOWN": "BLOCK", "ERROR": "ERROR",
}

DEFAULT_DECISION_POLICY = {"decision_policy_id": "ctal-default", "version": 1, "warn_action": "HOLD_FOR_REVIEW"}


def decide(aqpd_status: Optional[str], cles_status: Optional[str], checks_ok: bool = True,
           decision_policy: Optional[dict] = None) -> Tuple[str, List[str]]:
    """Return (outcome, reason_codes). Total over all inputs; anything unrecognised never proceeds."""
    dp = decision_policy or DEFAULT_DECISION_POLICY
    reasons: List[str] = []
    outcomes = []

    if aqpd_status not in AQPD_STATUSES:
        outcomes.append("ERROR")
        reasons.append("AQPD_RESULT_MISSING_OR_INVALID")
    else:
        o = _AQPD_OUTCOME[aqpd_status]
        if aqpd_status == "WARN" and dp.get("warn_action") == "PROCEED":
            o = "PROCEED"
            reasons.append("AQPD_WARN_PERMITTED_BY_POLICY")
        elif o != "PROCEED":
            reasons.append("AQPD_" + aqpd_status)
        outcomes.append(o)

    if cles_status not in CLES_STATUSES:
        outcomes.append("ERROR")
        reasons.append("CLES_RESULT_MISSING_OR_INVALID")
    else:
        o = _CLES_OUTCOME[cles_status]
        if o != "PROCEED":
            reasons.append("CLES_" + cles_status)
        outcomes.append(o)

    if not checks_ok:
        outcomes.append("BLOCK")
        reasons.append("ENVELOPE_OR_TENANT_OR_POLICY_CHECK_FAILED")

    outcome = max(outcomes, key=lambda x: _SEVERITY[x])
    if outcome == "PROCEED":
        reasons = reasons or ["AQPD_ACCEPT_AND_CLES_AUTHORIZED"]
    return outcome, reasons
