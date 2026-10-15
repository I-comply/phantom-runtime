import hashlib
import hmac
import json
import os
import time

os.environ["GATEWAY_KEYS"] = json.dumps({"service_node_01": "test-secret"})

from fastapi.testclient import TestClient  # noqa: E402

from gateway import app  # noqa: E402

client = TestClient(app)
CID = "service_node_01"
SECRET = b"test-secret"


def _post(body: bytes, ts=None, cid=CID, secret=SECRET, sig=None):
    ts = ts or str(int(time.time()))
    sig = sig or hmac.new(secret, body + ts.encode(), hashlib.sha256).hexdigest()
    return client.post(
        "/v1/policy/evaluate",
        content=body,
        headers={"X-Client-ID": cid, "X-Signature": sig, "X-Timestamp": ts, "Content-Type": "application/json"},
    )


def _body(action="read", cid=CID):
    return json.dumps({"client_id": cid, "action": action, "payload_checksum": "123456"}).encode()


def test_missing_auth_headers():
    r = client.post("/v1/policy/evaluate", json={"client_id": CID, "action": "read", "payload_checksum": "abc"})
    assert r.status_code == 401


def test_successful_policy_evaluation():
    r = _post(_body())
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED"


def test_denied_action():
    r = _post(_body("delete"))
    assert r.status_code == 200 and r.json()["status"] == "DENIED"


def test_bad_signature():
    assert _post(_body(), sig="0" * 64).status_code == 401


def test_stale_timestamp():
    assert _post(_body(), ts=str(int(time.time()) - 1000)).status_code == 403


def test_invalid_timestamp():
    assert _post(_body(), ts="abc", sig="x").status_code == 400


def test_unknown_client():
    assert _post(_body(cid="ghost"), cid="ghost").status_code == 403


def test_client_id_mismatch():
    client.app  # noqa: B018
    from gateway import KEY_STORE

    KEY_STORE["other"] = b"s2"
    r = _post(_body(cid=CID), cid="other", secret=b"s2")
    assert r.status_code == 403


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}
