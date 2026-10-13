"""Adapters from the supplied JavaScript AQPD.js / CLES.js to the CTAL AQPD and CLES contracts.

The JS files are kept byte-identical in ``adapters/js``. Each call runs ``bridge.mjs`` in a short-lived
Node process: hard timeout (process is killed), capped output, minimal environment (no inherited secrets).
Every bridge failure maps to ERROR (never success). AQPD assessments are signature-verified by the bridge
before use. See docs/ctal/js-integration.md for the status mapping and known gaps in the JS code.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from ..aqpd import AqpdResult
from ..canon import sha256_hex
from ..cles import ClesResult
from ..timeutil import fmt_ts, now_utc

_JS_DIR = os.path.join(os.path.dirname(__file__), "js")
BRIDGE = os.path.join(_JS_DIR, "bridge.mjs")
MAX_SUBJECT = 262_144
AQPD_POLICY_LABEL = "aqpd-policy-1.0.0"   # hard-coded inside AQPD.js


class BridgeError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class NodeBridge:
    def __init__(self, node: Optional[str] = None, timeout: float = 5.0, script: str = BRIDGE, max_output: int = 1_000_000):
        self.node = node or os.environ.get("CTAL_NODE") or shutil.which("node")
        self.timeout, self.script, self.max_output = timeout, script, max_output

    def available(self) -> bool:
        return bool(self.node) and os.path.exists(self.script)

    def call(self, req: dict) -> dict:
        if not self.available():
            raise BridgeError("NODE_UNAVAILABLE")
        try:
            p = subprocess.run([self.node, self.script], input=json.dumps(req).encode(), capture_output=True,
                               timeout=self.timeout, cwd=_JS_DIR, env={"PATH": os.environ.get("PATH", "")})
        except subprocess.TimeoutExpired:
            raise BridgeError("BRIDGE_TIMEOUT")
        except OSError:
            raise BridgeError("NODE_UNAVAILABLE")
        if p.returncode != 0 or len(p.stdout) > self.max_output:
            raise BridgeError("BRIDGE_FAILED")
        try:
            out = json.loads(p.stdout)
        except ValueError:
            raise BridgeError("BRIDGE_BAD_OUTPUT")
        if not isinstance(out, dict):
            raise BridgeError("BRIDGE_BAD_OUTPUT")
        return out


def _int_in(v, lo, hi) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


class JsAqpdEngine:
    """AqpdEngine backed by AQPD.js. decision allow->ACCEPT, review->REVIEW, deny->REJECT (AQPD.js emits no WARN/QUARANTINE)."""
    engine_version = "aqpd-js/" + AQPD_POLICY_LABEL
    _MAP = {"allow": "ACCEPT", "review": "REVIEW", "deny": "REJECT"}

    def __init__(self, bridge: NodeBridge, key_id: str, private_key_path: str, public_key_pem: str,
                 source: str = "ctal-gate", workflow: str = "content-release-gate"):
        self.bridge, self.key_id, self.private_key_path, self.public_key_pem = bridge, key_id, private_key_path, public_key_pem
        self.source, self.workflow = source, workflow

    def assess(self, content: bytes, media_type: str, policy: dict) -> AqpdResult:
        base = dict(assessment_id="asm-js-none", policy_id=policy["policy_id"], policy_version=int(policy["version"]),
                    engine_version=self.engine_version)

        def res(status, reasons, refs=()):
            return AqpdResult(status=status, reason_codes=list(reasons), evidence_refs=list(refs), **base)

        max_bytes = policy.get("max_bytes", MAX_SUBJECT)
        rv, dn = policy.get("review_threshold"), policy.get("deny_threshold")
        if not _int_in(max_bytes, 1, MAX_SUBJECT) or (rv is not None and not _int_in(rv, 0, 100)) \
                or (dn is not None and not _int_in(dn, 0, 100)) or (rv is not None and dn is not None and rv > dn):
            return res("ERROR", ["AQPD_POLICY_INVALID"])
        if not isinstance(content, (bytes, bytearray)):
            return res("ERROR", ["SUBJECT_NOT_BYTES"])
        if len(content) > max_bytes:   # AQPD.js would still run every regex over the full input; bound it here
            return res("REJECT", ["SUBJECT_TOO_LARGE"])
        try:
            bytes(content).decode("utf-8")   # AQPD.js silently substitutes U+FFFD for invalid bytes
        except UnicodeDecodeError:
            return res("REJECT", ["INVALID_UTF8"])
        try:
            out = self.bridge.call({
                "op": "aqpd.assess", "content_b64": base64.b64encode(bytes(content)).decode(), "key_id": self.key_id,
                "private_key_path": self.private_key_path, "public_key_pem": self.public_key_pem,
                "source": self.source, "workflow": self.workflow, "max_bytes": max_bytes,
                "review_threshold": rv, "deny_threshold": dn})
        except BridgeError as e:
            return res("ERROR", ["AQPD_" + e.code])
        if not out.get("ok"):
            return res("ERROR", ["AQPD_BRIDGE:" + str(out.get("error", "UNKNOWN"))[:80]])
        a = out.get("assessment")
        if not isinstance(a, dict) or a.get("contentDigest") != sha256_hex(bytes(content)):
            return res("ERROR", ["AQPD_DIGEST_MISMATCH"])
        status = self._MAP.get(a.get("decision"))
        if status is None:
            return res("UNKNOWN", ["AQPD_DECISION_UNRECOGNIZED"])
        findings = a.get("findings") if isinstance(a.get("findings"), list) else []
        reasons = ["AQPD_JS_DECISION_" + str(a["decision"]).upper()] + [str(f.get("ruleId"))[:64] for f in findings if isinstance(f, dict)]
        refs = ["aqpd:assessment:" + str(a.get("assessmentId")), "aqpd:score:" + str(a.get("score")),
                "aqpd:policy:" + str(a.get("policyVersion")), "aqpd:key:" + str(a.get("keyId"))]
        return AqpdResult(assessment_id=str(a.get("assessmentId")), status=status, reason_codes=reasons,
                          evidence_refs=refs, policy_id=base["policy_id"], policy_version=base["policy_version"],
                          engine_version=self.engine_version)


def _iso_ms(ms) -> Optional[str]:
    try:
        return fmt_ts(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class JsClesVerifier:
    """ClesVerifier backed by CLES.js. tenant_id is mapped to the license ``subject``.

    keys: {key_id: {"pem": <SPKI public PEM>, "status": "active"|"retired"|"revoked"}}; revoked keys are withheld
    from CLES.js so licenses signed by them fail. maxActivations is reported and enforced by the gate.
    """
    def __init__(self, bridge: NodeBridge, issuer: str, keys: dict, deployment: str, feature: str,
                 revoked_provider: Callable[[], Iterable[str]] = lambda: (), clock: Callable = now_utc):
        self.bridge, self.issuer, self.keys = bridge, issuer, keys
        self.deployment, self.feature, self.revoked_provider, self.clock = deployment, feature, revoked_provider, clock

    def verify(self, token_bytes, tenant_id: str, product_id: str) -> ClesResult:
        try:
            return self._verify(token_bytes, tenant_id, product_id)
        except Exception:
            return ClesResult("ERROR", ["CLES_INTERNAL_ERROR"], entitlement_checked=False)

    def _verify(self, token_bytes, tenant_id, product_id) -> ClesResult:
        if not token_bytes:
            return ClesResult("DENIED", ["ENTITLEMENT_MISSING"], entitlement_checked=False)
        if not isinstance(token_bytes, (bytes, bytearray)) or len(token_bytes) > 16_384:
            return ClesResult("DENIED", ["MALFORMED_TOKEN:SIZE_OR_TYPE"], entitlement_checked=False)

        def nodup(pairs):
            d = {}
            for k, v in pairs:
                if k in d:
                    raise ValueError("dup")
                d[k] = v
            return d
        try:
            lic = json.loads(bytes(token_bytes).decode("utf-8"), object_pairs_hook=nodup)
        except (ValueError, RecursionError):
            return ClesResult("DENIED", ["MALFORMED_TOKEN"], entitlement_checked=False)
        if not isinstance(lic, dict):
            return ClesResult("DENIED", ["MALFORMED_TOKEN:STRUCTURE"], entitlement_checked=False)
        try:
            revoked = [str(x) for x in self.revoked_provider()]
        except Exception:
            return ClesResult("ERROR", ["REVOCATION_CHECK_FAILED"], entitlement_checked=False)
        now = self.clock()
        pubs = {kid: k["pem"] for kid, k in self.keys.items() if k.get("status", "active") != "revoked"}
        try:
            out = self.bridge.call({
                "op": "cles.verify", "license": lic, "issuer": self.issuer, "subject": tenant_id, "product": product_id,
                "deployment": self.deployment, "feature": self.feature, "now": int(now.timestamp() * 1000),
                "public_keys": pubs, "revoked": revoked})
        except BridgeError as e:
            return ClesResult("ERROR", ["CLES_" + e.code], entitlement_checked=False)
        if not out.get("ok") or not isinstance(out.get("result"), dict):
            return ClesResult("ERROR", ["CLES_BRIDGE:" + str(out.get("error", "UNKNOWN"))[:80]], entitlement_checked=False)
        code = out["result"].get("code")
        s = out.get("license") if isinstance(out.get("license"), dict) else None
        common = {}
        if s:
            ma = s.get("maxActivations")
            common = dict(license_id=str(s.get("licenseId")), product_id=product_id, issuer_id=str(s.get("issuer")),
                          key_id=str(s.get("keyId")), valid_from=_iso_ms(s.get("notBefore")), valid_until=_iso_ms(s.get("expiresAt")),
                          max_activations=ma if isinstance(ma, int) and not isinstance(ma, bool) and ma >= 1 else None)
        stamp = fmt_ts(now)
        if code == "LICENSE_VALID" and out["result"].get("authorized") is True and s:
            return ClesResult("AUTHORIZED", ["ENTITLEMENT_VALID"], revocation_checked_at=stamp, **common)
        table = {
            "UNSUPPORTED_LICENSE_SCHEMA": ("DENIED", "UNSUPPORTED_LICENSE_SCHEMA"),
            "UNKNOWN_ISSUER_KEY": ("INVALID_SIGNATURE", "UNKNOWN_OR_REVOKED_KEY_ID"),
            "INVALID_LICENSE_SIGNATURE": ("INVALID_SIGNATURE", "BAD_SIGNATURE"),
            "ISSUER_MISMATCH": ("DENIED", "ISSUER_MISMATCH"),
            "LICENSE_REVOKED": ("REVOKED", "ENTITLEMENT_REVOKED"),
            "SUBJECT_MISMATCH": ("DENIED", "TENANT_MISMATCH"),
            "PRODUCT_MISMATCH": ("DENIED", "PRODUCT_MISMATCH"),
            "DEPLOYMENT_MISMATCH": ("DENIED", "DEPLOYMENT_MISMATCH"),
            "FEATURE_NOT_ENTITLED": ("DENIED", "FEATURE_NOT_ENTITLED"),
        }
        if code == "LICENSE_NOT_CURRENT":   # CLES.js reports expired and not-yet-valid identically; split on verified fields
            st, rc = ("EXPIRED", "ENTITLEMENT_EXPIRED") if (s and s.get("expired")) else ("DENIED", "NOT_YET_VALID_OR_INVALID_WINDOW")
        elif code in table:
            st, rc = table[code]
        else:
            return ClesResult("UNKNOWN", ["CLES_CODE_UNRECOGNIZED"], **common)
        return ClesResult(st, [rc], revocation_checked_at=stamp if st == "REVOKED" else None, **common)
