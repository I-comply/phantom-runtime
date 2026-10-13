"""CLES contract (Cryptographic Licensing and Entitlement System) and a REFERENCE verifier.

BLOCKED/SPECIFIED: the production CLES was not present in the supplied
repository. ``ClesVerifier`` here is NEW reference code implementing the CLES
contract (signed, tenant/product-scoped, time-bounded, revocable entitlement
tokens). It is independent of AQPD and shares only the key/trust primitives.

Token: {"payload": {...}, "signing": {"algorithm","key_id","signature"}}; the
signature covers the ``ctal-cjson-1`` canonical payload. Order of checks:
size/parse -> structure -> issuer key + signature -> tenant -> product ->
validity window -> revocation. Unverified payload fields are never acted on
before the signature verifies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Protocol

from .canon import CanonError, canonical_bytes, parse_strict
from .contracts import CLES_STATUSES
from .keys import ALGORITHM, TrustStore, VerifyError
from .timeutil import fmt_ts, now_utc, parse_ts

ENTITLEMENT_SCHEMA = "cles.entitlement.v1"
_PAYLOAD_REQUIRED = ("schema_version", "license_id", "tenant_id", "product_id", "issuer_id", "valid_from", "valid_until")


@dataclass
class ClesResult:
    authorization_status: str
    reason_codes: List[str] = field(default_factory=list)
    entitlement_checked: bool = True
    license_id: Optional[str] = None
    product_id: Optional[str] = None
    issuer_id: Optional[str] = None
    key_id: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    revocation_checked_at: Optional[str] = None
    max_activations: Optional[int] = None     # not part of the envelope; enforced by the gate

    def __post_init__(self):
        if self.authorization_status not in CLES_STATUSES:
            raise ValueError("INVALID_CLES_STATUS")


class RevocationSource(Protocol):
    def is_revoked(self, license_id: str) -> bool: ...


class StaticRevocationList:
    def __init__(self, revoked=()):
        self.revoked = set(revoked)

    def is_revoked(self, license_id: str) -> bool:
        return license_id in self.revoked


class ClesVerifier:
    def __init__(self, trust: TrustStore, revocations: RevocationSource, clock: Callable = now_utc):
        self.trust, self.revocations, self.clock = trust, revocations, clock

    def verify(self, token_bytes, tenant_id: str, product_id: str) -> ClesResult:
        try:
            return self._verify(token_bytes, tenant_id, product_id)
        except Exception:  # any internal failure is typed ERROR, never success
            return ClesResult("ERROR", ["CLES_INTERNAL_ERROR"], entitlement_checked=False)

    def _verify(self, token_bytes, tenant_id, product_id) -> ClesResult:
        if token_bytes is None or token_bytes == b"" or token_bytes == "":
            return ClesResult("DENIED", ["ENTITLEMENT_MISSING"], entitlement_checked=False)
        try:
            token = parse_strict(token_bytes, max_bytes=16_384)
        except CanonError as e:
            return ClesResult("DENIED", ["MALFORMED_TOKEN:" + e.code], entitlement_checked=False)
        if (not isinstance(token, dict) or set(token) != {"payload", "signing"}
                or not isinstance(token["payload"], dict) or not isinstance(token["signing"], dict)):
            return ClesResult("DENIED", ["MALFORMED_TOKEN:STRUCTURE"], entitlement_checked=False)
        sig = token["signing"]
        if set(sig) != {"algorithm", "key_id", "signature"} or not all(isinstance(v, str) for v in sig.values()):
            return ClesResult("DENIED", ["MALFORMED_TOKEN:SIGNING"], entitlement_checked=False)
        if sig["algorithm"] != ALGORITHM:  # expected algorithm comes from trusted config, not the token
            return ClesResult("INVALID_SIGNATURE", ["UNSUPPORTED_ALGORITHM"], key_id=sig["key_id"])
        payload = token["payload"]
        now = self.clock()
        try:
            self.trust.verify(sig["key_id"], "entitlement", canonical_bytes(payload), sig["signature"], now)
        except VerifyError as e:
            return ClesResult("INVALID_SIGNATURE", [e.code], key_id=sig["key_id"])
        # signature valid: payload now attributable to the issuer key
        if any(not isinstance(payload.get(f), (str, int)) or payload.get(f) == "" for f in _PAYLOAD_REQUIRED) \
                or payload["schema_version"] != ENTITLEMENT_SCHEMA:
            return ClesResult("DENIED", ["MALFORMED_PAYLOAD"], key_id=sig["key_id"])
        try:
            vf, vu = parse_ts(payload["valid_from"]), parse_ts(payload["valid_until"])
        except ValueError:
            return ClesResult("DENIED", ["MALFORMED_PAYLOAD:TIMESTAMP"], key_id=sig["key_id"])
        common = dict(license_id=payload["license_id"], product_id=payload["product_id"],
                      issuer_id=payload["issuer_id"], key_id=sig["key_id"],
                      valid_from=payload["valid_from"], valid_until=payload["valid_until"])
        if payload["tenant_id"] != tenant_id:
            return ClesResult("DENIED", ["TENANT_MISMATCH"], **common)
        if payload["product_id"] != product_id:
            return ClesResult("DENIED", ["PRODUCT_MISMATCH"], **common)
        if now < vf:
            return ClesResult("DENIED", ["NOT_YET_VALID"], **common)
        if now > vu:
            return ClesResult("EXPIRED", ["ENTITLEMENT_EXPIRED"], **common)
        try:
            revoked = self.revocations.is_revoked(payload["license_id"])
        except Exception:
            return ClesResult("ERROR", ["REVOCATION_CHECK_FAILED"], entitlement_checked=False, **common)
        stamp = fmt_ts(now)
        ma = payload.get("max_activations")
        if isinstance(ma, int) and not isinstance(ma, bool) and ma >= 1:
            common["max_activations"] = ma
        if revoked:
            return ClesResult("REVOKED", ["ENTITLEMENT_REVOKED"], revocation_checked_at=stamp, **common)
        return ClesResult("AUTHORIZED", ["ENTITLEMENT_VALID"], revocation_checked_at=stamp, **common)


def issue_entitlement(signer, *, license_id, tenant_id, product_id, issuer_id, valid_from, valid_until,
                      max_activations=None) -> bytes:
    """Issuer-side helper (used by tests/demo; real issuance belongs in the licensing service)."""
    payload = {"schema_version": ENTITLEMENT_SCHEMA, "license_id": license_id, "tenant_id": tenant_id,
               "product_id": product_id, "issuer_id": issuer_id, "valid_from": valid_from, "valid_until": valid_until}
    if max_activations is not None:
        payload["max_activations"] = max_activations
    tok = {"payload": payload, "signing": {"algorithm": ALGORITHM, "key_id": signer.key_id,
                                           "signature": signer.sign(canonical_bytes(payload))}}
    return canonical_bytes(tok)
