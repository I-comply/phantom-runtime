import os
import tempfile
from datetime import datetime, timedelta, timezone

from ctal.aqpd import ReferenceAqpdEngine
from ctal.cles import ClesVerifier, StaticRevocationList, issue_entitlement
from ctal.gate import Gate
from ctal.keys import Signer, TrustedKey, TrustStore
from ctal.store import Store
from ctal.timeutil import fmt_ts

T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
POLICY = {"max_bytes": 5000, "reject_patterns": ["ignore previous instructions"], "warn_patterns": ["click here"]}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class World:
    """Deterministic fixture: store, keys, gate, two tenants (acme, globex)."""

    def __init__(self, aqpd=None, aqpd_timeout=2.0, decision_policy=None):
        self.tmp = tempfile.mkdtemp(prefix="ctal-test-")
        self.clock = Clock()
        self.store = Store(os.path.join(self.tmp, "t.db"), clock=self.clock)
        self.store.migrate_up()
        self.env_s, self.exp_s, self.iss = Signer.generate("env-1"), Signer.generate("exp-1"), Signer.generate("iss-1")
        self.public, self.issuer_trust = TrustStore(), TrustStore()
        self.public.add(TrustedKey("env-1", self.env_s.public_raw(), "envelope"))
        self.public.add(TrustedKey("exp-1", self.exp_s.public_raw(), "export"))
        self.issuer_trust.add(TrustedKey("iss-1", self.iss.public_raw(), "entitlement"))
        self.revoked = StaticRevocationList()
        self.cles = ClesVerifier(self.issuer_trust, self.revoked, clock=self.clock)
        self.gate = Gate(self.store, aqpd or ReferenceAqpdEngine(), self.cles, self.env_s, self.public,
                         release_digest="a" * 64, aqpd_timeout=aqpd_timeout, clock=self.clock,
                         decision_policy=decision_policy)
        self.keys = {t: self.store.create_api_key(t, "admin", t + "-admin") for t in ("acme", "globex")}
        self.auth = {t: self.store.authenticate(k) for t, k in self.keys.items()}
        for t in ("acme", "globex"):
            self.store.for_tenant(self.auth[t]).publish_policy("pol", dict(POLICY), "setup", "setup")

    def token(self, license_id="lic-1", tenant="acme", product="prod", days_from=-1, days_to=30, signer=None):
        return issue_entitlement(signer or self.iss, license_id=license_id, tenant_id=tenant, product_id=product,
                                 issuer_id="issuer", valid_from=fmt_ts(self.clock() + timedelta(days=days_from)),
                                 valid_until=fmt_ts(self.clock() + timedelta(days=days_to)))

    def run(self, tenant="acme", content=b"hello world", token="default", idem="k1", product="prod", **kw):
        return self.gate.process(self.auth[tenant], content=content, media_type="text/plain",
                                 entitlement_token=self.token(tenant=tenant) if token == "default" else token,
                                 product_id=product, policy_id="pol", idempotency_key=idem,
                                 correlation_id="corr-" + idem, **kw)

    def ledger(self, tenant="acme"):
        return self.store.for_tenant(self.auth[tenant])
