import hashlib
import hmac
import json
import os
import time

os.environ["GATEWAY_KEYS"] = json.dumps({"service_node_01": "test-secret"})

import pytest  # noqa: E402
import fakeredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import gateway  # noqa: E402
from gateway import REPLAY_CACHE, RedisReplayCache, ReplayCache, app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_replay_cache():
    REPLAY_CACHE._seen.clear()
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


def test_replay_rejected():
    body = _body()
    ts = str(int(time.time()))
    assert _post(body, ts=ts).status_code == 200
    assert _post(body, ts=ts).status_code == 409


def test_distinct_timestamps_not_replay():
    body = _body()
    now = int(time.time())
    assert _post(body, ts=str(now - 1)).status_code == 200
    assert _post(body, ts=str(now)).status_code == 200


def test_invalid_signature_not_cached():
    ts = str(int(time.time()))
    assert _post(_body(), ts=ts, sig="0" * 64).status_code == 401
    assert _post(_body(), ts=ts).status_code == 200


def test_replay_cache_expiry_and_saturation():
    from fastapi import HTTPException

    import asyncio

    async def run():
        c = ReplayCache(ttl=0.01, max_entries=2)
        assert await c.check_and_add("a", "s1")
        assert not await c.check_and_add("a", "s1")
        await asyncio.sleep(0.02)
        assert await c.check_and_add("a", "s1")
        c2 = ReplayCache(ttl=60, max_entries=1)
        assert await c2.check_and_add("a", "s1")
        with pytest.raises(HTTPException):
            await c2.check_and_add("a", "s2")

    asyncio.run(run())


def test_redis_replay_cache(monkeypatch):
    fake = fakeredis.FakeAsyncRedis()
    monkeypatch.setattr(gateway, "REPLAY_CACHE", RedisReplayCache(fake, ttl=60))
    body = _body()
    ts = str(int(time.time()))
    assert _post(body, ts=ts).status_code == 200
    assert _post(body, ts=ts).status_code == 409


def test_redis_down_fails_closed(monkeypatch):
    class Broken:
        async def set(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(gateway, "REPLAY_CACHE", RedisReplayCache(Broken()))
    assert _post(_body()).status_code == 503
