"""Operational value metrics and license reminders, computed only from ledger events (no invented baselines).

Definitions (see docs/ctal/pilot-runbook.md):
- decisions: count of ``assurance_envelope_signed`` events in the window, by decision outcome.
- hold_rate = HOLD_FOR_REVIEW / decisions; block_rate; error_rate = ERROR / decisions.
- latency_ms p50/p95: gate processing time recorded in the signed-envelope event (excludes network and queueing).
- regression: approved cases (``regression_case_added``) and proposals (``remediation_created``).
Coverage and manual-review time need customer-side data and are NOT computed here.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import List, Optional

from .timeutil import fmt_ts, now_utc, parse_ts


def _pct(vals: List[int], p: float) -> Optional[int]:
    if not vals:
        return None
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))]


def summary(events: List[dict], from_time: Optional[str] = None, to_time: Optional[str] = None) -> dict:
    ev = [e for e in events if (not from_time or e["event_time"] >= from_time) and (not to_time or e["event_time"] <= to_time)]
    signed = [e for e in ev if e["event_type"] == "assurance_envelope_signed"]
    n = len(signed)
    outcomes = Counter(e["outcome"] for e in signed)
    lat = [e["payload"]["latency_ms"] for e in signed if isinstance(e["payload"].get("latency_ms"), int)]
    reasons = Counter(r for e in ev if e["event_type"] in ("assessment_completed", "entitlement_denied", "assurance_envelope_signed")
                      for r in e["reason_codes"])
    rate = lambda k: round(outcomes.get(k, 0) / n, 4) if n else None
    return {
        "window": {"from": from_time, "to": to_time},
        "decisions": n, "by_outcome": dict(outcomes),
        "by_aqpd_status": dict(Counter(e["outcome"] for e in ev if e["event_type"] == "assessment_completed")),
        "by_policy_version": {str(k): v for k, v in Counter(e["policy_version"] for e in signed).items()},
        "proceed_rate": rate("PROCEED"), "hold_rate": rate("HOLD_FOR_REVIEW"), "block_rate": rate("BLOCK"), "error_rate": rate("ERROR"),
        "latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "samples": len(lat)},
        "top_reason_codes": Counter(reasons).most_common(10),
        "regression": {"proposed": sum(1 for e in ev if e["event_type"] == "remediation_created"),
                       "approved": sum(1 for e in ev if e["event_type"] == "regression_case_added")},
        "tenant_gate_failures": sum(1 for e in ev if e["event_type"] == "envelope_verification_failed"),
        "not_computed": ["coverage (needs customer workflow counts)", "manual review time", "investigation duration",
                         "false positive/negative rates (needs labeled ground truth)"],
    }


def expiring_licenses(events: List[dict], within_days: int = 30, now=None) -> List[dict]:
    """Licenses seen in ``entitlement_verified`` events whose recorded valid_until is within ``within_days`` (or already past)."""
    now = now or now_utc()
    horizon = fmt_ts(now + timedelta(days=within_days))
    latest = {}
    for e in events:
        if e["event_type"] == "entitlement_verified" and e["payload"].get("license_id") and e["payload"].get("valid_until"):
            latest[e["payload"]["license_id"]] = e
    revoked = {e["payload"].get("license_id") for e in events if e["event_type"] == "entitlement_denied"
               and "LICENSE_REVOKED_BY_ADMIN" in e["reason_codes"]}
    out = []
    for lid, e in latest.items():
        vu = e["payload"]["valid_until"]
        if lid in revoked or vu > horizon:
            continue
        days = (parse_ts(vu) - now).total_seconds() / 86400
        out.append({"license_id": lid, "valid_until": vu, "days_remaining": round(days, 1), "expired": days < 0,
                    "last_seen": e["event_time"]})
    return sorted(out, key=lambda x: x["valid_until"])
