"""Fail-closed orchestration of AQPD + CLES into a signed, ledgered decision.

AQPD and CLES run as separate adapters and their results are recorded
separately in the envelope. Any exception, timeout, invalid result, policy
mismatch or self-verification failure yields a typed non-PROCEED outcome or a
GateError; nothing converts an error into success. The protected action is
recorded only when the persisted envelope verified and its outcome is PROCEED,
inside the same transaction as the envelope (exactly-once for that record).
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import time
from typing import Callable, Optional

from .aqpd import AqpdEngine, AqpdResult
from .canon import digest_obj, sha256_hex
from .cles import ClesResult, ClesVerifier
from .contracts import AQPD_STATUSES, CLES_STATUSES, DEFAULT_DECISION_POLICY
from .envelope import build_and_sign, verify_envelope
from .keys import Signer, TrustedKey, TrustStore, fingerprint
from .store import AuthContext, Store, TenantLedger
from .timeutil import now_utc

MAX_SUBJECT_BYTES = 262_144
_IDEM = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class GateError(Exception):
    def __init__(self, code: str, http: int):
        super().__init__(code)
        self.code, self.http = code, http


def source_release_digest() -> str:
    """sha256 over the CTAL source tree (a source digest, NOT a signed build attestation)."""
    forced = os.environ.get("CTAL_RELEASE_DIGEST")
    if forced:
        if not re.match(r"^[0-9a-f]{64}$", forced):
            raise ValueError("CTAL_RELEASE_DIGEST must be 64 lowercase hex chars")
        return forced
    from .release import tree_digest
    return tree_digest()


class Gate:
    def __init__(self, store: Store, aqpd: AqpdEngine, cles: ClesVerifier, envelope_signer: Signer,
                 envelope_trust: TrustStore, release_digest: Optional[str] = None, aqpd_timeout: float = 2.0,
                 clock: Callable = now_utc, decision_policy: Optional[dict] = None):
        self.store, self.aqpd, self.cles = store, aqpd, cles
        self.signer, self.trust = envelope_signer, envelope_trust
        self.release_digest = release_digest or source_release_digest()
        self.aqpd_timeout, self.clock = aqpd_timeout, clock
        self.decision_policy = decision_policy or DEFAULT_DECISION_POLICY
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="aqpd")

    @staticmethod
    def _ledger_entitlement_checks(led: TenantLedger, cl: ClesResult, inst: str) -> ClesResult:
        """Live revocation (admin-managed, permanent) and activation limits (maxActivations), applied to any engine."""
        if cl.authorization_status != "AUTHORIZED":
            return cl
        keep = {k: getattr(cl, k) for k in ("license_id", "product_id", "issuer_id", "key_id", "valid_from", "valid_until",
                                            "revocation_checked_at", "max_activations")}
        try:
            if cl.license_id and led.is_revoked(cl.license_id):
                return ClesResult("REVOKED", ["ENTITLEMENT_REVOKED"], **keep)
            if cl.max_activations and cl.license_id and not led.register_activation(cl.license_id, inst, cl.max_activations):
                return ClesResult("DENIED", ["ACTIVATION_LIMIT_EXCEEDED"], **keep)
        except Exception:
            return ClesResult("ERROR", ["ENTITLEMENT_LEDGER_CHECK_FAILED"], entitlement_checked=False)
        return cl

    def assess_only(self, led: TenantLedger, content: bytes, media_type: str, policy_id: str, version: Optional[int] = None):
        """AQPD only, no entitlement, no envelope, no side effect (used for regression replay)."""
        pol = led.get_policy(policy_id, version)
        if pol is None:
            raise GateError("POLICY_NOT_FOUND", 422)
        return pol, self._run_aqpd(content, media_type, pol)

    def rotate_envelope_key(self, new_signer: Signer, ledgers, actor: str) -> None:
        """Overlapping rotation: old key becomes 'retired' (still verifies), new key signs from now on."""
        old = self.signer.key_id
        self.trust.add(TrustedKey(new_signer.key_id, new_signer.public_raw(), "envelope"))
        self.trust.set_status(old, "retired")
        self.signer = new_signer
        for led in ledgers:
            led.append([led.new_event("key_rotated", actor=actor, correlation_id="key-rotation",
                                      payload={"old_key_id": old, "new_key_id": new_signer.key_id,
                                               "new_public_key_sha256": fingerprint(new_signer.public_raw())})])

    def revoke_key(self, key_id: str, ledgers, actor: str, reason: str) -> None:
        """Revoked keys fail verification everywhere, including for previously signed envelopes (strict model)."""
        self.trust.set_status(key_id, "revoked")
        for led in ledgers:
            led.append([led.new_event("key_revoked", actor=actor, correlation_id="key-revocation",
                                      reason_codes=[reason], payload={"key_id": key_id})])

    def _run_aqpd(self, content, media_type, pol) -> AqpdResult:
        base = dict(assessment_id="asm-failed", policy_id=pol["policy_id"], policy_version=pol["version"],
                    engine_version=getattr(self.aqpd, "engine_version", "unknown"))
        fut = self._pool.submit(self.aqpd.assess, content, media_type,
                                {**pol["body"], "policy_id": pol["policy_id"], "version": pol["version"]})
        try:
            r = fut.result(timeout=self.aqpd_timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            return AqpdResult(status="ERROR", reason_codes=["AQPD_TIMEOUT"], **base)
        except Exception:
            return AqpdResult(status="ERROR", reason_codes=["AQPD_EXCEPTION"], **base)
        if not isinstance(r, AqpdResult) or r.status not in AQPD_STATUSES \
                or (r.policy_id, r.policy_version) != (pol["policy_id"], pol["version"]):
            return AqpdResult(status="ERROR", reason_codes=["AQPD_RESULT_INVALID_OR_POLICY_MISMATCH"], **base)
        return r

    def process(self, auth: AuthContext, *, content, media_type: str, entitlement_token, product_id: str,
                policy_id: str, idempotency_key: str, correlation_id: str, claimed_tenant: Optional[str] = None,
                instance_id: Optional[str] = None) -> dict:
        if not auth.allows("gate"):
            raise GateError("FORBIDDEN", 403)
        led = self.store.for_tenant(auth)
        if claimed_tenant is not None and claimed_tenant != auth.tenant_id:
            led.append([led.new_event("envelope_verification_failed", actor=auth.label, correlation_id=correlation_id,
                                      outcome="BLOCK", reason_codes=["TENANT_MISMATCH"])])
            raise GateError("TENANT_MISMATCH", 403)
        if not isinstance(idempotency_key, str) or not _IDEM.match(idempotency_key):
            raise GateError("BAD_IDEMPOTENCY_KEY", 400)
        if not isinstance(content, (bytes, bytearray)) or len(content) > MAX_SUBJECT_BYTES:
            raise GateError("SUBJECT_INVALID_OR_TOO_LARGE", 413)
        if not isinstance(product_id, str) or not product_id or not isinstance(policy_id, str) or not policy_id:
            raise GateError("BAD_REQUEST", 400)
        pol = led.get_policy(policy_id)
        if pol is None:
            raise GateError("POLICY_NOT_FOUND", 422)
        content = bytes(content)
        token_b = entitlement_token if isinstance(entitlement_token, (bytes, type(None))) else None
        req_digest = digest_obj({"subject": sha256_hex(content), "media_type": media_type or "", "product_id": product_id,
                                 "policy_id": policy_id, "entitlement": sha256_hex(token_b or b"")})
        state, env_id = led.claim(idempotency_key, req_digest)
        if state == "conflict":
            raise GateError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST", 409)
        if state == "in_progress":
            raise GateError("REQUEST_IN_PROGRESS", 409)
        if state == "replay":
            return {"replayed": True, "envelope": led.get_envelope(env_id)}
        try:
            inst = instance_id if isinstance(instance_id, str) and _IDEM.match(instance_id) else auth.principal
            return self._decide(led, auth, content, media_type, token_b, product_id, pol, idempotency_key,
                                correlation_id, inst)
        except BaseException:
            led.release(idempotency_key)
            raise

    def _decide(self, led: TenantLedger, auth, content, media_type, token_b, product_id, pol, idem, corr, inst) -> dict:
        t0 = time.monotonic()
        digest = sha256_hex(content)
        aq = self._run_aqpd(content, media_type, pol)
        try:
            cl = self.cles.verify(token_b, auth.tenant_id, product_id)
            if not isinstance(cl, ClesResult) or cl.authorization_status not in CLES_STATUSES:
                raise TypeError("invalid CLES result")
        except Exception:
            cl = ClesResult("ERROR", ["CLES_ADAPTER_FAILURE"], entitlement_checked=False)
        cl = self._ledger_entitlement_checks(led, cl, inst)
        bundle = digest_obj({"aqpd_policy_digest": pol["digest"], "decision_policy": self.decision_policy})
        env = build_and_sign(
            tenant_id=auth.tenant_id, subject_digest=digest, media_type=media_type or None,
            subject_evidence_refs=["sha256:" + digest], aqpd=aq, cles=cl, policy_bundle_digest=bundle,
            software_release_digest=self.release_digest, decision_policy=self.decision_policy,
            signer=self.signer, clock=self.clock)
        vr = verify_envelope(env, self.trust, expected_tenant=auth.tenant_id, decision_policy=self.decision_policy,
                             now=self.clock())
        actor = auth.label
        common = dict(actor=actor, correlation_id=corr, subject_digest=digest)
        if not vr.ok:
            led.append([led.new_event("envelope_verification_failed", outcome="ERROR", reason_codes=vr.errors,
                                      release_digest=self.release_digest, **common)])
            raise GateError("ENVELOPE_SELF_VERIFICATION_FAILED", 500)
        outcome = env["decision"]["outcome"]
        evs = [
            led.new_event("subject_received", payload={"media_type": media_type or "", "bytes": len(content)}, **common),
            led.new_event("assessment_started", policy_id=pol["policy_id"], policy_version=pol["version"], **common),
            led.new_event("assessment_completed", policy_id=aq.policy_id, policy_version=aq.policy_version,
                          outcome=aq.status, reason_codes=aq.reason_codes,
                          payload={"assessment_id": aq.assessment_id, "engine_version": aq.engine_version}, **common),
            led.new_event("entitlement_verified" if cl.authorization_status == "AUTHORIZED" else "entitlement_denied",
                          outcome=cl.authorization_status, reason_codes=cl.reason_codes,
                          payload={"license_id": cl.license_id or "", "key_id": cl.key_id or "", "valid_until": cl.valid_until or ""}, **common),
            led.new_event("assurance_envelope_signed", policy_id=pol["policy_id"], policy_version=pol["version"],
                          release_digest=self.release_digest, outcome=outcome,
                          reason_codes=env["decision"]["reason_codes"],
                          payload={"envelope_id": env["envelope_id"], "envelope_digest": digest_obj(env),
                                   "decision_policy": self.decision_policy,
                                   "latency_ms": int((time.monotonic() - t0) * 1000)}, **common),
        ]
        with self.store.tx() as c:
            led.put_envelope(c, env)
            led.append(evs, c)
            if outcome == "PROCEED":
                led.record_protected_action(c, idem, env["envelope_id"], "release_subject:" + digest)
            led.complete(c, idem, env["envelope_id"])
        return {"replayed": False, "envelope": env}
