"""The `admin` role is per workspace. Only an admin key in the platform workspace
(PHANTOM_PLATFORM_TENANT_ID) sees across tenants or mints keys for other workspaces."""
import uuid

from .conftest import mint_key, eid


def _ws(client):
    return client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()


def _event(client, key, entity, payload=None):
    r = client.post("/api/events/", json={"entity_id": entity, "event_type": "init", "payload": payload or {"x": 1}},
                    headers={"X-API-Key": key})
    assert r.status_code == 200, r.text


def test_workspace_admin_cannot_read_another_workspaces_data(client, bootstrap_key):
    ws_a, ws_b = _ws(client), _ws(client)
    admin_a = mint_key(client, None, ws_a["id"], role="admin")
    agent_b = mint_key(client, None, ws_b["id"])
    entity = eid()
    _event(client, agent_b, entity, {"secret": "B"})
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": admin_a}).status_code == 404
    assert client.get(f"/api/state/{entity}", headers={"X-API-Key": admin_a}).status_code == 404
    assert client.post("/api/snapshots/", json={"entity_id": entity}, headers={"X-API-Key": admin_a}).status_code == 404
    assert entity not in client.get("/api/state/", headers={"X-API-Key": admin_a}).json()
    assert not any(e["entity_id"] == entity for e in client.get("/api/events/", headers={"X-API-Key": admin_a}).json())
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": agent_b}).status_code == 200


def test_platform_admin_sees_across_workspaces(client, platform_key):
    ws_b = _ws(client)
    agent_b = mint_key(client, None, ws_b["id"])
    entity = eid()
    _event(client, agent_b, entity)
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": platform_key}).status_code == 200
    assert entity in client.get("/api/state/", headers={"X-API-Key": platform_key}).json()


def test_admin_role_has_no_cross_tenant_power_when_no_platform_workspace_is_configured(client, monkeypatch):
    monkeypatch.delenv("PHANTOM_PLATFORM_TENANT_ID", raising=False)
    ws_a, ws_b = _ws(client), _ws(client)
    admin_a = mint_key(client, None, ws_a["id"], role="admin")
    entity = eid()
    _event(client, mint_key(client, None, ws_b["id"]), entity)
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": admin_a}).status_code == 404


def test_workspace_admin_cannot_mint_keys_for_another_workspace(client):
    ws_a, ws_b = _ws(client), _ws(client)
    admin_a = mint_key(client, None, ws_a["id"], role="admin")
    body = {"tenant_id": ws_b["id"], "role": "admin", "name": "x"}
    assert client.post("/api/v3/security/api-keys", json=body, headers={"X-API-Key": admin_a}).status_code == 403
    own = {"tenant_id": ws_a["id"], "role": "agent", "name": "own"}
    assert client.post("/api/v3/security/api-keys", json=own, headers={"X-API-Key": admin_a}).status_code == 200


def test_workspace_admin_cannot_mint_a_platform_admin_key(client, platform_key, monkeypatch):
    import os
    platform_ws = os.environ["PHANTOM_PLATFORM_TENANT_ID"]
    admin_a = mint_key(client, None, _ws(client)["id"], role="admin")
    body = {"tenant_id": platform_ws, "role": "admin", "name": "sneaky"}
    assert client.post("/api/v3/security/api-keys", json=body, headers={"X-API-Key": admin_a}).status_code == 403


def test_platform_admin_can_mint_keys_for_any_workspace(client, platform_key):
    ws_b = _ws(client)
    r = client.post("/api/v3/security/api-keys", json={"tenant_id": ws_b["id"], "role": "agent", "name": "x"},
                    headers={"X-API-Key": platform_key})
    assert r.status_code == 200


def test_workspace_admin_cannot_use_other_tenants_plugins_or_strategies(client):
    ws_a, ws_b = _ws(client), _ws(client)
    admin_a, admin_b = mint_key(client, None, ws_a["id"], role="admin"), mint_key(client, None, ws_b["id"], role="admin")
    pid = client.post("/api/plugins/", json={"name": "p", "code": "result={}"}, headers={"X-API-Key": admin_b}).json()["id"]
    entity = eid()
    _event(client, admin_a, entity)
    assert client.post(f"/api/plugins/{pid}/execute", json={"entity_id": entity}, headers={"X-API-Key": admin_a}).status_code == 404
    assert client.get(f"/api/plugins/{pid}/executions", headers={"X-API-Key": admin_a}).status_code == 404
    sid = client.post("/api/v3/strategies", json={"name": "s", "strategy_type": "custom", "code": "result={}"},
                      headers={"X-API-Key": admin_b}).json()["id"]
    assert client.post(f"/api/v3/strategies/{sid}/execute", params={"entity_id": entity},
                       headers={"X-API-Key": admin_a}).status_code == 404


def test_admin_plugin_created_without_workspace_belongs_to_its_own_workspace_only(client, platform_key):
    ws_a = _ws(client)
    admin_a = mint_key(client, None, ws_a["id"], role="admin")
    pid = client.post("/api/plugins/", json={"name": "p", "code": "result={}", "workspace_id": str(uuid.uuid4())},
                      headers={"X-API-Key": admin_a}).json()["id"]  # a workspace admin cannot name another owner
    entity = eid()
    _event(client, admin_a, entity)
    assert client.post(f"/api/plugins/{pid}/execute", json={"entity_id": entity}, headers={"X-API-Key": admin_a}).status_code == 200


def test_any_key_cannot_snapshot_another_tenants_entity_and_read_it_back(client):
    ws_a, ws_b = _ws(client), _ws(client)
    agent_a, agent_b = mint_key(client, None, ws_a["id"]), mint_key(client, None, ws_b["id"])
    entity = eid()
    _event(client, agent_a, entity, {"secret": "A"})
    assert client.post("/api/snapshots/", json={"entity_id": entity}, headers={"X-API-Key": agent_b}).status_code == 404
    assert client.get(f"/api/snapshots/entity/{entity}/latest", headers={"X-API-Key": agent_b}).status_code == 404
    assert client.post("/api/snapshots/", json={"entity_id": entity}, headers={"X-API-Key": agent_a}).status_code == 200
