"""Ed25519 signing boundary and trust store (maintained library: ``cryptography``).

The algorithm is fixed by trusted configuration (``ALGORITHM``); it is never
read from untrusted input. Keys carry a purpose so an entitlement-issuer key
cannot vouch for envelopes or exports. Private keys are only ever held by a
``Signer`` and written, if at all, to a 0600 PEM file outside the repository.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .timeutil import now_utc, parse_ts

ALGORITHM = "Ed25519"
PURPOSES = ("envelope", "entitlement", "export")


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def unb64u(s: str) -> bytes:
    if not isinstance(s, str) or not s or "=" in s:
        raise ValueError("BAD_B64")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class VerifyError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def fingerprint(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()


class Signer:
    def __init__(self, key_id: str, private: Ed25519PrivateKey):
        self.key_id = key_id
        self._priv = private

    @classmethod
    def generate(cls, key_id: str) -> "Signer":
        return cls(key_id, Ed25519PrivateKey.generate())

    @classmethod
    def load_pem(cls, path: str, key_id: str) -> "Signer":
        with open(path, "rb") as f:
            return cls(key_id, serialization.load_pem_private_key(f.read(), password=None))

    def save_pem(self, path: str) -> None:
        pem = self._priv.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)

    def public_raw(self) -> bytes:
        return self._priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def sign(self, message: bytes) -> str:
        return b64u(self._priv.sign(message))

    def __repr__(self) -> str:  # never expose key material
        return "Signer(key_id=%r)" % self.key_id


@dataclass
class TrustedKey:
    key_id: str
    public_raw: bytes
    purpose: str
    status: str = "active"          # active | retired (verify-only) | revoked (never valid)
    not_before: Optional[str] = None
    not_after: Optional[str] = None

    def to_json(self) -> dict:
        d = {"key_id": self.key_id, "algorithm": ALGORITHM, "public_key": b64u(self.public_raw),
             "purpose": self.purpose, "status": self.status}
        if self.not_before:
            d["not_before"] = self.not_before
        if self.not_after:
            d["not_after"] = self.not_after
        return d


class TrustStore:
    def __init__(self):
        self._keys: Dict[str, TrustedKey] = {}

    def add(self, key: TrustedKey) -> None:
        if key.purpose not in PURPOSES or key.status not in ("active", "retired", "revoked"):
            raise ValueError("BAD_KEY_DEFINITION")
        if len(key.public_raw) != 32:
            raise ValueError("BAD_PUBLIC_KEY")
        self._keys[key.key_id] = key

    def set_status(self, key_id: str, status: str) -> None:
        self._keys[key_id].status = status

    def get(self, key_id: str) -> Optional[TrustedKey]:
        return self._keys.get(key_id)

    def verify(self, key_id: str, purpose: str, message: bytes, signature_b64u: str,
               at: Optional[datetime] = None) -> TrustedKey:
        k = self._keys.get(key_id)
        if k is None:
            raise VerifyError("UNKNOWN_KEY_ID")
        if k.purpose != purpose:
            raise VerifyError("KEY_PURPOSE_MISMATCH")
        if k.status == "revoked":
            raise VerifyError("KEY_REVOKED")
        at = at or now_utc()
        if k.not_before and at < parse_ts(k.not_before):
            raise VerifyError("KEY_NOT_YET_VALID")
        if k.not_after and at > parse_ts(k.not_after):
            raise VerifyError("KEY_EXPIRED")
        try:
            sig = unb64u(signature_b64u)
        except Exception:
            raise VerifyError("MALFORMED_SIGNATURE")
        if len(sig) != 64:
            raise VerifyError("MALFORMED_SIGNATURE")
        try:
            Ed25519PublicKey.from_public_bytes(k.public_raw).verify(sig, message)
        except InvalidSignature:
            raise VerifyError("BAD_SIGNATURE")
        return k

    def to_json(self) -> dict:
        return {"schema_version": "ctal.trust.v1", "keys": [k.to_json() for k in self._keys.values()]}

    @classmethod
    def from_json(cls, doc: dict) -> "TrustStore":
        ts = cls()
        for k in doc["keys"]:
            if k.get("algorithm") != ALGORITHM:
                raise ValueError("UNSUPPORTED_ALGORITHM")
            ts.add(TrustedKey(k["key_id"], unb64u(k["public_key"]), k["purpose"], k.get("status", "active"),
                              k.get("not_before"), k.get("not_after")))
        return ts

    @classmethod
    def load(cls, path: str) -> "TrustStore":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_json(json.load(f))
