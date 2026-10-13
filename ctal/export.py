"""Signed, customer-owned evidence export (zip) for one tenant.

Contents: manifest.json (file digests, signed by the export key), events.jsonl,
envelopes.jsonl, policies.json, checkpoint.json (signed head of the event
chain), trust/keys.json (public keys only), schemas/*, VERIFY.txt.
No private key material is ever written. Verify offline with verifier/ctal_verify.py.
"""
from __future__ import annotations

import io
import os
import zipfile
from typing import Callable

from .canon import CANONICALIZATION_ID, canonical_bytes, sha256_hex
from .keys import ALGORITHM, Signer, TrustStore
from .store import TenantLedger
from .timeutil import fmt_ts, now_utc

_HERE = os.path.dirname(__file__)
_VERIFY_TXT = """CTAL evidence export. Verify offline (no network, no database, no private keys):
  python3 ctal_verify.py <this.zip> --pin-export-key-id <ID> --pin-export-public-key <BASE64URL>
The pinned export public key must be obtained out-of-band (not from this archive).
A passing result establishes integrity and attribution of the listed items only; read 'not_established'.
"""


def _rb(path):
    with open(path, "rb") as f:
        return f.read()


def sign_doc(doc: dict, signer: Signer) -> dict:
    """Signature covers the canonical doc with signing.signature absent."""
    unsigned = dict(doc)
    unsigned["signing"] = {"algorithm": ALGORITHM, "key_id": signer.key_id, "canonicalization_id": CANONICALIZATION_ID}
    sig = signer.sign(canonical_bytes(unsigned))
    unsigned["signing"]["signature"] = sig
    return unsigned


def build_export(ledger: TenantLedger, export_signer: Signer, public_trust: TrustStore, *, actor: str,
                 correlation_id: str, clock: Callable = now_utc) -> bytes:
    ledger.append([ledger.new_event("export_created", actor=actor, correlation_id=correlation_id,
                                    reason_codes=[], payload={"format": "ctal.export.v1"})])
    events = ledger.all_events()
    head = events[-1]
    chain = ledger.verify_chain()
    if not chain["ok"]:
        raise RuntimeError("LEDGER_CHAIN_BROKEN_REFUSING_EXPORT")
    now = fmt_ts(clock())
    cp = sign_doc({"schema_version": "ctal.checkpoint.v1", "tenant_id": ledger.tenant_id, "head_seq": head["seq"],
                   "head_hash": head["hash"], "issued_at": now}, export_signer)
    ledger.add_checkpoint(cp)
    files = {
        "events.jsonl": b"".join(canonical_bytes(e) + b"\n" for e in events),
        "envelopes.jsonl": b"".join(canonical_bytes(e) + b"\n" for e in ledger.all_envelopes()),
        "policies.json": canonical_bytes(ledger.all_policies()),
        "checkpoint.json": canonical_bytes(cp),
        "trust/keys.json": canonical_bytes(public_trust.to_json()),
        "schemas/assurance-envelope.v1.schema.json": _rb(os.path.join(_HERE, "schemas", "assurance-envelope.v1.schema.json")),
        "VERIFY.txt": _VERIFY_TXT.encode(),
    }
    manifest = sign_doc({
        "schema_version": "ctal.export.v1", "tenant_id": ledger.tenant_id, "created_at": now,
        "files": {n: {"sha256": sha256_hex(b), "bytes": len(b)} for n, b in sorted(files.items())},
    }, export_signer)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", canonical_bytes(manifest))
        for n, b in sorted(files.items()):
            z.writestr(n, b)
    return buf.getvalue()
