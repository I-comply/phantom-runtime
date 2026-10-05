import os, uuid
from .util import canon, sha256, mac, now_ms


def req_string(t, a, v, action, params, ts, nonce):
    return "\n".join(["ATLv1", t, a, str(v), action, str(ts), nonce, sha256(canon(params))])


def intent_digest(t, a, action, params):
    return sha256(canon({"tenant_id": t, "agent_id": a, "action": action, "params": params}))


def approval_string(t, ap, v, digest, exp):
    return "\n".join(["ATLAPPROVE1", t, ap, str(v), digest, str(exp)])


def sign_request(secret, tenant, agent, ver, action, params, idempotency_key=None, ts=None, nonce=None, approval=None):
    ts = ts if ts is not None else now_ms()
    nonce = nonce or uuid.uuid4().hex
    r = {"tenant_id": tenant, "agent_id": agent, "key_version": ver, "action": action, "params": params,
         "timestamp": ts, "nonce": nonce,
         "signature": mac(secret, req_string(tenant, agent, ver, action, params, ts, nonce))}
    if idempotency_key:
        r["idempotency_key"] = idempotency_key
    if approval:
        r["approval"] = approval
    return r


def sign_approval(secret, tenant, approver, ver, agent, action, params, expires_at):
    d = intent_digest(tenant, agent, action, params)
    return {"approver_id": approver, "key_version": ver, "expires_at": expires_at,
            "signature": mac(secret, approval_string(tenant, approver, ver, d, expires_at))}
