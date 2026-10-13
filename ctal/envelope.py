"""Assurance envelope ``ctal.envelope.v1``: build, sign, verify.

The signature covers the canonical (ctal-cjson-1) envelope with ``signing.signature``
removed; ``signing.algorithm``, ``signing.key_id`` and ``signing.canonicalization_id``
are inside the signed bytes. Verification additionally recomputes the decision from
the separately recorded AQPD and CLES statuses: a validly signed envelope that
claims PROCEED for a non-PROCEED combination is rejected.
A valid signature proves integrity/attribution under the trust store, not that the content is true or safe.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional

from .canon import CANONICALIZATION_ID, CanonError, canonical_bytes
from .contracts import AQPD_STATUSES, CLES_STATUSES, OUTCOMES, decide
from .keys import ALGORITHM, Signer, TrustStore, VerifyError
from .timeutil import fmt_ts, now_utc, parse_ts

SCHEMA_VERSION = "ctal.envelope.v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def validate_schema(env) -> List[str]:
    """Hand-written validator (authoritative); schemas/assurance-envelope.v1.schema.json documents the same contract."""
    e: List[str] = []

    def need(d, key, typ, path):
        if not isinstance(d, dict) or key not in d:
            e.append("missing:" + path + key)
            return None
        if not isinstance(d[key], typ) or isinstance(d[key], bool) and typ is not bool:
            e.append("type:" + path + key)
            return None
        return d[key]

    def only(d, allowed, path):
        for k in d:
            if k not in allowed:
                e.append("unexpected:" + path + k)

    if not isinstance(env, dict):
        return ["not_object"]
    only(env, {"envelope_id", "schema_version", "tenant_id", "subject", "aqpd", "cles", "policy_bundle_digest",
               "software_release_digest", "decision", "issued_at", "signing"}, "")
    for k in ("envelope_id", "tenant_id"):
        v = need(env, k, str, "")
        if v == "":
            e.append("empty:" + k)
    if need(env, "schema_version", str, "") not in (None, SCHEMA_VERSION):
        e.append("unsupported_schema_version")
    for k in ("policy_bundle_digest", "software_release_digest"):
        v = need(env, k, str, "")
        if v is not None and not _HEX64.match(v):
            e.append("bad_digest:" + k)
    s = need(env, "subject", dict, "")
    if s is not None:
        only(s, {"digest_algorithm", "digest", "media_type", "evidence_refs"}, "subject.")
        if need(s, "digest_algorithm", str, "subject.") not in (None, "SHA-256"):
            e.append("bad_value:subject.digest_algorithm")
        d = need(s, "digest", str, "subject.")
        if d is not None and not _HEX64.match(d):
            e.append("bad_digest:subject.digest")
        if "media_type" in s and not isinstance(s["media_type"], str):
            e.append("type:subject.media_type")
        if "evidence_refs" not in s or not _is_str_list(s["evidence_refs"]):
            e.append("type:subject.evidence_refs")
    a = need(env, "aqpd", dict, "")
    if a is not None:
        only(a, {"assessment_id", "status", "policy_id", "policy_version", "engine_version", "reason_codes",
                 "evidence_refs"}, "aqpd.")
        for k in ("assessment_id", "policy_id", "engine_version"):
            need(a, k, str, "aqpd.")
        need(a, "policy_version", int, "aqpd.")
        if need(a, "status", str, "aqpd.") not in (None,) + AQPD_STATUSES:
            e.append("bad_value:aqpd.status")
        for k in ("reason_codes", "evidence_refs"):
            if k not in a or not _is_str_list(a[k]):
                e.append("type:aqpd." + k)
    c = need(env, "cles", dict, "")
    if c is not None:
        only(c, {"authorization_status", "license_id", "product_id", "entitlement_checked", "issuer_id", "key_id",
                 "valid_from", "valid_until", "revocation_checked_at", "reason_codes"}, "cles.")
        if need(c, "authorization_status", str, "cles.") not in (None,) + CLES_STATUSES:
            e.append("bad_value:cles.authorization_status")
        need(c, "entitlement_checked", bool, "cles.")
        for k in ("license_id", "product_id", "issuer_id", "key_id", "valid_from", "valid_until",
                  "revocation_checked_at"):
            if k in c and not isinstance(c[k], str):
                e.append("type:cles." + k)
        if "reason_codes" not in c or not _is_str_list(c["reason_codes"]):
            e.append("type:cles.reason_codes")
    d = need(env, "decision", dict, "")
    if d is not None:
        only(d, {"outcome", "reason_codes", "evaluated_at"}, "decision.")
        if need(d, "outcome", str, "decision.") not in (None,) + OUTCOMES:
            e.append("bad_value:decision.outcome")
        if "reason_codes" not in d or not _is_str_list(d["reason_codes"]):
            e.append("type:decision.reason_codes")
        for k in ("evaluated_at",):
            v = need(d, k, str, "decision.")
            if v is not None:
                try:
                    parse_ts(v)
                except ValueError:
                    e.append("bad_timestamp:decision." + k)
    v = need(env, "issued_at", str, "")
    if v is not None:
        try:
            parse_ts(v)
        except ValueError:
            e.append("bad_timestamp:issued_at")
    g = need(env, "signing", dict, "")
    if g is not None:
        only(g, {"algorithm", "key_id", "signature", "canonicalization_id"}, "signing.")
        for k in ("algorithm", "key_id", "signature", "canonicalization_id"):
            need(g, k, str, "signing.")
    return e


def signing_input(env: dict) -> bytes:
    unsigned = {k: v for k, v in env.items() if k != "signing"}
    unsigned["signing"] = {k: v for k, v in env["signing"].items() if k != "signature"}
    return canonical_bytes(unsigned)


def build_and_sign(*, tenant_id, subject_digest, media_type, subject_evidence_refs, aqpd, cles, policy_bundle_digest,
                   software_release_digest, decision_policy, signer: Signer, checks_ok=True,
                   clock: Callable = now_utc) -> dict:
    outcome, reasons = decide(aqpd.status, cles.authorization_status, checks_ok, decision_policy)
    now = fmt_ts(clock())
    cl = {"authorization_status": cles.authorization_status, "entitlement_checked": bool(cles.entitlement_checked),
          "reason_codes": list(cles.reason_codes)}
    for k in ("license_id", "product_id", "issuer_id", "key_id", "valid_from", "valid_until", "revocation_checked_at"):
        v = getattr(cles, k)
        if v is not None:
            cl[k] = v
    subj = {"digest_algorithm": "SHA-256", "digest": subject_digest, "evidence_refs": list(subject_evidence_refs)}
    if media_type:
        subj["media_type"] = media_type
    env = {
        "envelope_id": "env-" + uuid.uuid4().hex, "schema_version": SCHEMA_VERSION, "tenant_id": tenant_id,
        "subject": subj,
        "aqpd": {"assessment_id": aqpd.assessment_id, "status": aqpd.status, "policy_id": aqpd.policy_id,
                 "policy_version": aqpd.policy_version, "engine_version": aqpd.engine_version,
                 "reason_codes": list(aqpd.reason_codes), "evidence_refs": list(aqpd.evidence_refs)},
        "cles": cl, "policy_bundle_digest": policy_bundle_digest, "software_release_digest": software_release_digest,
        "decision": {"outcome": outcome, "reason_codes": reasons, "evaluated_at": now},
        "issued_at": now,
        "signing": {"algorithm": ALGORITHM, "key_id": signer.key_id, "signature": "",
                    "canonicalization_id": CANONICALIZATION_ID},
    }
    env["signing"]["signature"] = signer.sign(signing_input(env))
    return env


@dataclass
class VerifyResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    checks: List[str] = field(default_factory=list)


def verify_envelope(env, trust: TrustStore, *, expected_tenant: Optional[str] = None,
                    decision_policy: Optional[dict] = None, now: Optional[datetime] = None,
                    max_age_seconds: Optional[int] = None) -> VerifyResult:
    r = VerifyResult(ok=False)
    errs = validate_schema(env)
    if errs:
        r.errors = ["SCHEMA:" + x for x in errs]
        return r
    r.checks.append("schema")
    sg = env["signing"]
    if sg["algorithm"] != ALGORITHM:
        r.errors.append("ALGORITHM_NOT_ALLOWED")
        return r
    if sg["canonicalization_id"] != CANONICALIZATION_ID:
        r.errors.append("CANONICALIZATION_NOT_ALLOWED")
        return r
    if expected_tenant is not None and env["tenant_id"] != expected_tenant:
        r.errors.append("TENANT_MISMATCH")
        return r
    r.checks.append("tenant")
    try:
        msg = signing_input(env)
        trust.verify(sg["key_id"], "envelope", msg, sg["signature"], now)
    except CanonError as e:
        r.errors.append("CANON:" + e.code)
        return r
    except VerifyError as e:
        r.errors.append(e.code)
        return r
    r.checks.append("signature")
    exp, _ = decide(env["aqpd"]["status"], env["cles"]["authorization_status"], True, decision_policy)
    if env["decision"]["outcome"] != exp:
        r.errors.append("DECISION_INCONSISTENT_WITH_AQPD_CLES")
        return r
    r.checks.append("decision_matrix")
    if max_age_seconds is not None:
        age = ((now or now_utc()) - parse_ts(env["issued_at"])).total_seconds()
        if age > max_age_seconds or age < -60:
            r.errors.append("ENVELOPE_STALE_OR_FUTURE")
            return r
        r.checks.append("freshness")
    r.ok = True
    return r
