"""Runtime wiring from environment variables (names only; values are never logged).

CTAL_ENV              development | production (default development)
CTAL_DB               SQLite path
CTAL_ENVELOPE_KEY     PEM path for the envelope signing key   (0600, outside the repo)
CTAL_EXPORT_KEY       PEM path for the export signing key
CTAL_ISSUER_TRUST     JSON trust file with CLES issuer public keys (purpose "entitlement")
CTAL_REVOKED_LICENSES JSON file: ["license-id", ...]
CTAL_ENGINE           reference (default) | js  (see _js_engines for the js settings)
In production, keys whose id starts with "dev-" are refused and missing key files are an error.
In development, missing key files are generated with ids "dev-..." and a loud log line.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Tuple

from .aqpd import ReferenceAqpdEngine
from .cles import ClesVerifier, StaticRevocationList
from .gate import Gate
from .keys import Signer, TrustedKey, TrustStore
from .store import Store

log = logging.getLogger("ctal")


def load_signer(path: str, key_id: str, env: str) -> Signer:
    if env == "production" and key_id.startswith("dev-"):
        raise RuntimeError("development key id refused in production")
    if not os.path.exists(path):
        if env == "production":
            raise RuntimeError("signing key file missing in production: " + path)
        log.warning("generating DEVELOPMENT-ONLY signing key at %s", path)
        s = Signer.generate(key_id)
        s.save_pem(path)
        return s
    if env == "production" and (os.stat(path).st_mode & 0o077):
        raise RuntimeError("signing key file permissions too open: " + path)
    return Signer.load_pem(path, key_id)


def build_from_env(environ=os.environ) -> Tuple[Gate, Signer, TrustStore]:
    env = environ.get("CTAL_ENV", "development")
    store = Store(environ.get("CTAL_DB", "ctal.db"))
    store.migrate_up()
    es = load_signer(environ.get("CTAL_ENVELOPE_KEY", "envelope.key.pem"), environ.get("CTAL_ENVELOPE_KEY_ID", "dev-envelope-1"), env)
    xs = load_signer(environ.get("CTAL_EXPORT_KEY", "export.key.pem"), environ.get("CTAL_EXPORT_KEY_ID", "dev-export-1"), env)
    public = TrustStore()
    public.add(TrustedKey(es.key_id, es.public_raw(), "envelope"))
    public.add(TrustedKey(xs.key_id, xs.public_raw(), "export"))
    issuer_trust = TrustStore.load(environ["CTAL_ISSUER_TRUST"]) if environ.get("CTAL_ISSUER_TRUST") else TrustStore()
    revoked = json.load(open(environ["CTAL_REVOKED_LICENSES"])) if environ.get("CTAL_REVOKED_LICENSES") else []
    if environ.get("CTAL_ENGINE", "reference") == "js":
        aqpd, cles = _js_engines(environ)
    else:
        aqpd, cles = ReferenceAqpdEngine(), ClesVerifier(issuer_trust, StaticRevocationList(revoked))
    gate = Gate(store, aqpd, cles, es, public)
    return gate, xs, public


def _js_engines(environ):
    """CTAL_ENGINE=js: AQPD.js/CLES.js via the Node bridge. All names below are required; values are never logged.
    CTAL_AQPD_KEY_ID, CTAL_AQPD_PRIVATE_KEY (PEM path, 0600), CTAL_AQPD_PUBLIC_KEY (PEM path),
    CTAL_CLES_ISSUER, CTAL_CLES_KEYS (JSON {"keys":[{"key_id","pem","status"}]}), CTAL_CLES_DEPLOYMENT,
    CTAL_CLES_FEATURE, CTAL_REVOKED_LICENSES (JSON list, re-read on every check), CTAL_NODE (optional)."""
    from .adapters.node_bridge import JsAqpdEngine, JsClesVerifier, NodeBridge
    bridge = NodeBridge()
    if not bridge.available():
        raise RuntimeError("CTAL_ENGINE=js but node is not available")
    with open(environ["CTAL_AQPD_PUBLIC_KEY"], encoding="utf-8") as f:
        apub = f.read()
    with open(environ["CTAL_CLES_KEYS"], encoding="utf-8") as f:
        keys = {k["key_id"]: {"pem": k["pem"], "status": k.get("status", "active")} for k in json.load(f)["keys"]}
    rev_path = environ.get("CTAL_REVOKED_LICENSES")

    def revoked():
        if not rev_path:
            return []
        with open(rev_path, encoding="utf-8") as fh:
            return json.load(fh)
    aqpd = JsAqpdEngine(bridge, environ["CTAL_AQPD_KEY_ID"], environ["CTAL_AQPD_PRIVATE_KEY"], apub)
    cles = JsClesVerifier(bridge, environ["CTAL_CLES_ISSUER"], keys, environ["CTAL_CLES_DEPLOYMENT"],
                          environ["CTAL_CLES_FEATURE"], revoked)
    return aqpd, cles
