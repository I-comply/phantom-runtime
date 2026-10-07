"""WebSockets require an API key (first message) and only ever send the caller's own workspace's data."""
import asyncio
import uuid

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api import websocket as ws_mod
from .conftest import mint_key, eid


@pytest.fixture(autouse=True)
def fast_ws(monkeypatch):
    monkeypatch.setattr(ws_mod, "WS_AUTH_TIMEOUT_S", 0.4)
    monkeypatch.setattr(ws_mod, "METRICS_CACHE_TTL_S", 0)
    monkeypatch.setattr(ws_mod, "METRICS_INTERVAL_S", 0.05)


def _ws(client):
    return client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()


def _event(client, key, entity):
    assert client.post("/api/events/", json={"entity_id": entity, "event_type": "init", "payload": {"x": 1}},
                       headers={"X-API-Key": key}).status_code == 200


def _auth(ws, key):
    ws.send_json({"type": "auth", "api_key": key})


@pytest.mark.parametrize("path", ["/ws/metrics", "/ws/events"])
def test_no_auth_message_is_closed(client, path):
    with client.websocket_connect(path) as ws:
        assert ws.receive_json()["type"] == "auth_error"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


@pytest.mark.parametrize("path", ["/ws/metrics", "/ws/events"])
@pytest.mark.parametrize("bad", [{"type": "auth", "api_key": "sk_nope"}, {"type": "hello"}, {"api_key": 5}, "not json"])
def test_bad_credentials_are_closed(client, path, bad):
    with client.websocket_connect(path) as ws:
        ws.send_json(bad) if isinstance(bad, dict) else ws.send_text(bad)
        assert ws.receive_json()["type"] == "auth_error"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


def test_a_workspace_key_in_the_url_or_header_is_not_enough(client, workspace):
    key = mint_key(client, None, workspace["id"])
    with client.websocket_connect(f"/ws/metrics?api_key={key}", headers={"X-API-Key": key}) as ws:
        assert ws.receive_json()["type"] == "auth_error"


def test_metrics_are_scoped_to_the_callers_workspace(client, platform_key):
    ws_a, ws_b = _ws(client), _ws(client)
    key_a, key_b = mint_key(client, None, ws_a["id"]), mint_key(client, None, ws_b["id"])
    for _ in range(2):
        _event(client, key_a, eid())
    for _ in range(5):
        _event(client, key_b, eid())
    with client.websocket_connect("/ws/metrics") as ws:
        _auth(ws, key_a)
        assert ws.receive_json()["type"] == "auth_ok"
        data = ws.receive_json()["data"]
    assert data["total_events_v1"] == 2          # not 7, and not the platform-wide total
    assert data["active_connections"] == 0       # only this workspace's connections are counted
    with client.websocket_connect("/ws/metrics") as ws:
        _auth(ws, platform_key)
        ws.receive_json()
        platform = ws.receive_json()["data"]
    assert platform["total_events_v1"] >= 7      # the platform admin sees global figures


def test_events_stream_authenticates_then_heartbeats(client, workspace):
    key = mint_key(client, None, workspace["id"])
    with client.websocket_connect("/ws/events") as ws:
        _auth(ws, key)
        ok = ws.receive_json()
        assert ok["type"] == "auth_ok" and ok["tenant_id"] == workspace["id"] and ok["platform"] is False
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "heartbeat"


def test_a_workspace_admin_key_is_not_a_platform_key(client, workspace):
    key = mint_key(client, None, workspace["id"], role="admin")
    with client.websocket_connect("/ws/events") as ws:
        _auth(ws, key)
        assert ws.receive_json()["platform"] is False


def test_connection_limit_per_key(client, workspace, monkeypatch):
    monkeypatch.setattr(ws_mod, "MAX_WS_PER_KEY", 1)
    key = mint_key(client, None, workspace["id"])
    with client.websocket_connect("/ws/events") as first:
        _auth(first, key)
        assert first.receive_json()["type"] == "auth_ok"
        with client.websocket_connect("/ws/events") as second:
            _auth(second, key)
            assert second.receive_json()["error"] == "too_many_connections"
            with pytest.raises(WebSocketDisconnect) as exc:
                second.receive_json()
    assert exc.value.code == 1013


def test_oversized_auth_frame_is_rejected(client):
    with client.websocket_connect("/ws/events") as ws:
        ws.send_text("x" * 5000)
        assert ws.receive_json()["type"] == "auth_error"


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, m):
        self.sent.append(m)


def test_broadcast_reaches_only_the_events_tenant_and_platform_admins():
    async def run():
        m = ws_mod.ConnectionManager()
        a, b, plat = FakeWS(), FakeWS(), FakeWS()
        m.connections = [(a, ws_mod.Principal("k1", "tenant-a", False)), (b, ws_mod.Principal("k2", "tenant-b", False)),
                         (plat, ws_mod.Principal("k3", "platform", True))]
        await m.broadcast({"type": "new_event", "data": {"n": 1}}, "tenant-a")
        return a.sent, b.sent, plat.sent
    a, b, plat = asyncio.run(run())
    assert len(a) == 1 and len(plat) == 1 and b == []
