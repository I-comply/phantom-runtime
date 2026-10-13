#!/usr/bin/env python3
"""Independent offline verifier for CTAL evidence exports (ctal.export.v1).

Needs only Python 3.9+ and the `cryptography` package. Imports nothing from the
CTAL service, needs no database and no private key. The export public key MUST be
pinned by the operator (--pin-export-key-id/--pin-export-public-key), obtained
out-of-band; keys inside the archive are only trusted because the pinned key
signed the manifest that digests them.
Exit 0 only if every check passed. The JSON report lists what was checked and what is NOT established.
"""
import argparse
import base64
import hashlib
import json
import re
import sys
import unicodedata
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

CANON_ID = "ctal-cjson-1"
GENESIS = "0" * 64
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
EVENT_TYPES = {"subject_received", "assessment_started", "assessment_completed", "policy_created",
               "policy_version_published", "license_issued", "entitlement_verified", "entitlement_denied",
               "assurance_envelope_signed", "envelope_verification_failed", "remediation_created",
               "regression_case_added", "release_manifest_signed", "export_created", "key_rotated", "key_revoked"}
EXPECTED = {"manifest.json", "events.jsonl", "envelopes.jsonl", "policies.json", "checkpoint.json", "trust/keys.json",
            "schemas/assurance-envelope.v1.schema.json", "VERIFY.txt"}
NOT_ESTABLISHED = [
    "Truth, safety or legality of any assessed content (a signature proves integrity/attribution only).",
    "Correctness or accuracy of the AQPD engine or CLES issuer decisions.",
    "That no events were omitted before the checkpoint if the export signing key was compromised or the operator withheld events.",
    "Events appended after the checkpoint was issued.",
    "Accuracy of timestamps (they are asserted by the operator, not by a trusted time source).",
    "That the software_release_digest corresponds to any particular audited build (source digest only; no build attestation checked).",
    "Retention/deletion compliance, or regulatory compliance of any kind.",
]


class Fail(Exception):
    pass


# ---- independent canonicalization (ctal-cjson-1, RFC 8785 subset) ----
def _enc(o, d=0):
    if d > 32:
        raise Fail("canon: too deep")
    if o is None:
        return "null"
    if o is True:
        return "true"
    if o is False:
        return "false"
    if isinstance(o, int):
        if abs(o) > 2 ** 53 - 1:
            raise Fail("canon: int range")
        return str(o)
    if isinstance(o, float):
        raise Fail("canon: float")
    if isinstance(o, str):
        if unicodedata.normalize("NFC", o) != o:
            raise Fail("canon: non-NFC")
        o.encode("utf-8")
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, list):
        return "[" + ",".join(_enc(v, d + 1) for v in o) + "]"
    if isinstance(o, dict):
        ks = sorted(o, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _enc(o[k], d + 1) for k in ks) + "}"
    raise Fail("canon: type")


def canon(o):
    return _enc(o).encode("utf-8")


def _nodupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise Fail("duplicate key " + k)
        out[k] = v
    return out


def _nofloat(_):
    raise Fail("float/constant not allowed")


def parse(b):
    try:
        return json.loads(b.decode("utf-8"), object_pairs_hook=_nodupes, parse_float=_nofloat, parse_constant=_nofloat)
    except (ValueError, RecursionError, UnicodeDecodeError) as e:
        raise Fail("malformed json: %s" % type(e).__name__)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def check_sig(doc, pubkeys, purpose_keys, what):
    """pubkeys: {key_id: raw}. Signature covers canon(doc minus signing.signature)."""
    sg = doc.get("signing")
    if not isinstance(sg, dict) or sg.get("algorithm") != "Ed25519" or sg.get("canonicalization_id") != CANON_ID:
        raise Fail("%s: signing block missing or algorithm/canonicalization not allowed" % what)
    if sg.get("key_id") not in purpose_keys:
        raise Fail("%s: signing key %r not trusted for this purpose" % (what, sg.get("key_id")))
    unsigned = dict(doc)
    unsigned["signing"] = {k: v for k, v in sg.items() if k != "signature"}
    try:
        sig = unb64u(sg["signature"])
        Ed25519PublicKey.from_public_bytes(pubkeys[sg["key_id"]]).verify(sig, canon(unsigned))
    except (InvalidSignature, ValueError, KeyError, TypeError):
        raise Fail("%s: signature invalid" % what)


def decide(aq, cl, dp):
    A = {"ACCEPT": "PROCEED", "WARN": "HOLD_FOR_REVIEW", "REVIEW": "HOLD_FOR_REVIEW", "UNKNOWN": "HOLD_FOR_REVIEW",
         "QUARANTINE": "BLOCK", "REJECT": "BLOCK", "ERROR": "ERROR"}
    C = {"AUTHORIZED": "PROCEED", "DENIED": "BLOCK", "EXPIRED": "BLOCK", "REVOKED": "BLOCK",
         "INVALID_SIGNATURE": "BLOCK", "UNKNOWN": "BLOCK", "ERROR": "ERROR"}
    sev = {"PROCEED": 0, "HOLD_FOR_REVIEW": 1, "BLOCK": 2, "ERROR": 3}
    a = A.get(aq, "ERROR")
    if aq == "WARN" and dp.get("warn_action") == "PROCEED":
        a = "PROCEED"
    c = C.get(cl, "ERROR")
    return max((a, c), key=lambda x: sev[x])


def verify(path, pin_id, pin_pub_b64u, pin_env_key=None):
    checked, errors = [], []
    z = zipfile.ZipFile(path)
    names = [i.filename for i in z.infolist()]
    if len(names) != len(set(names)):
        raise Fail("duplicate archive member names")
    total = 0
    for i in z.infolist():
        if i.filename.startswith("/") or ".." in i.filename.split("/") or "\\" in i.filename:
            raise Fail("unsafe archive path " + i.filename)
        if i.file_size > MAX_FILE:
            raise Fail("member too large " + i.filename)
        total += i.file_size
    if total > MAX_TOTAL:
        raise Fail("archive too large")
    if set(names) != EXPECTED:
        raise Fail("archive members differ from expected set: extra=%s missing=%s" % (
            sorted(set(names) - EXPECTED), sorted(EXPECTED - set(names))))
    data = {n: z.read(n) for n in names}
    checked.append("archive structure and path safety")

    export_pub = {pin_id: unb64u(pin_pub_b64u)}
    manifest = parse(data["manifest.json"])
    check_sig(manifest, export_pub, {pin_id}, "manifest")
    checked.append("manifest signature by pinned export key %s" % pin_id)
    if manifest.get("schema_version") != "ctal.export.v1":
        raise Fail("unsupported export schema")
    tenant = manifest["tenant_id"]
    files = manifest["files"]
    if set(files) != EXPECTED - {"manifest.json"}:
        raise Fail("manifest file list mismatch")
    for n, meta in files.items():
        if sha(data[n]) != meta["sha256"] or len(data[n]) != meta["bytes"]:
            raise Fail("file digest mismatch: " + n)
    checked.append("sha256 + size of all %d files match signed manifest" % len(files))

    events = [parse(l) for l in data["events.jsonl"].splitlines() if l]
    prev = GENESIS
    for n, ev in enumerate(events, 1):
        if ev.get("tenant_id") != tenant:
            raise Fail("event %d belongs to another tenant" % n)
        if ev.get("seq") != n or ev.get("prev_hash") != prev:
            raise Fail("event chain broken (reorder/deletion/substitution) at seq %d" % n)
        if ev.get("event_type") not in EVENT_TYPES:
            raise Fail("unknown event type at seq %d" % n)
        if sha(canon({k: v for k, v in ev.items() if k != "hash"})) != ev.get("hash"):
            raise Fail("event hash mismatch (altered) at seq %d" % n)
        prev = ev["hash"]
    if not events:
        raise Fail("no events")
    checked.append("hash chain of %d events (contiguous seq, prev_hash links, recomputed hashes, single tenant)" % len(events))

    cp = parse(data["checkpoint.json"])
    check_sig(cp, export_pub, {pin_id}, "checkpoint")
    if cp.get("tenant_id") != tenant or cp.get("head_seq") != len(events) or cp.get("head_hash") != prev:
        raise Fail("signed checkpoint does not match event chain head (truncation or substitution)")
    checked.append("signed checkpoint matches chain head (seq %d)" % cp["head_seq"])

    trust = parse(data["trust/keys.json"])
    pubs, env_keys = {}, set()
    for k in trust["keys"]:
        if k.get("algorithm") != "Ed25519":
            raise Fail("unsupported key algorithm in trust file")
        pubs[k["key_id"]] = unb64u(k["public_key"])
        if k.get("purpose") == "envelope" and k.get("status", "active") != "revoked":
            env_keys.add(k["key_id"])
    if pin_env_key and (pin_env_key[0] not in env_keys or pubs.get(pin_env_key[0]) != unb64u(pin_env_key[1])):
        raise Fail("pinned envelope key not present/active in package trust file")

    policies = parse(data["policies.json"])
    pol = {}
    for p in policies:
        if sha(canon(p["body"])) != p["digest"] or p["body"].get("policy_id") != p["policy_id"] \
                or p["body"].get("version") != p["version"]:
            raise Fail("policy digest mismatch: %s v%s" % (p["policy_id"], p["version"]))
        pol[(p["policy_id"], p["version"])] = p["digest"]
    checked.append("%d policy versions: digests recomputed" % len(pol))

    signed_events = {}
    for ev in events:
        if ev["event_type"] == "assurance_envelope_signed":
            eid = ev["payload"]["envelope_id"]
            if eid in signed_events:
                raise Fail("duplicate assurance_envelope_signed event for " + eid)
            signed_events[eid] = ev
    envs = [parse(l) for l in data["envelopes.jsonl"].splitlines() if l]
    seen = set()
    for e in envs:
        eid = e.get("envelope_id")
        if e.get("tenant_id") != tenant:
            raise Fail("envelope %s belongs to another tenant" % eid)
        if e.get("schema_version") != "ctal.envelope.v1" or eid in seen:
            raise Fail("envelope schema/duplicate problem: %s" % eid)
        seen.add(eid)
        for f in ("policy_bundle_digest", "software_release_digest"):
            if not HEX64.match(str(e.get(f, ""))):
                raise Fail("envelope %s bad %s" % (eid, f))
        check_sig(e, pubs, env_keys, "envelope " + eid)
        se = signed_events.get(eid)
        if se is None or se["payload"]["envelope_digest"] != sha(canon(e)):
            raise Fail("envelope %s has no matching ledger event / digest differs" % eid)
        dp = se["payload"]["decision_policy"]
        if decide(e["aqpd"]["status"], e["cles"]["authorization_status"], dp) != e["decision"]["outcome"]:
            raise Fail("envelope %s outcome inconsistent with AQPD/CLES statuses" % eid)
        key = (e["aqpd"]["policy_id"], e["aqpd"]["policy_version"])
        if key not in pol:
            raise Fail("envelope %s references policy version not in export: %s" % (eid, key))
        if sha(canon({"aqpd_policy_digest": pol[key], "decision_policy": dp})) != e["policy_bundle_digest"]:
            raise Fail("envelope %s policy_bundle_digest does not match recorded policy + decision policy" % eid)
        if se["subject_digest"] != e["subject"]["digest"] or se["outcome"] != e["decision"]["outcome"]:
            raise Fail("envelope %s disagrees with its ledger event" % eid)
    if set(signed_events) != seen:
        raise Fail("ledger records signed envelopes that are absent from the export")
    checked.append("%d envelopes: Ed25519 signatures, decision matrix consistency, ledger linkage, policy bundle digests" % len(envs))
    return checked


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("archive")
    ap.add_argument("--pin-export-key-id", required=True)
    ap.add_argument("--pin-export-public-key", required=True, help="base64url raw Ed25519 public key")
    ap.add_argument("--pin-envelope-key-id")
    ap.add_argument("--pin-envelope-public-key")
    a = ap.parse_args(argv)
    pin_env = (a.pin_envelope_key_id, a.pin_envelope_public_key) if a.pin_envelope_key_id else None
    try:
        checked = verify(a.archive, a.pin_export_key_id, a.pin_export_public_key, pin_env)
        ok, err = True, None
    except (Fail, zipfile.BadZipFile, KeyError, TypeError, ValueError) as e:
        checked, ok, err = [], False, "%s: %s" % (type(e).__name__, e)
    print(json.dumps({"verified": ok, "error": err, "checked": checked, "not_established": NOT_ESTABLISHED}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
