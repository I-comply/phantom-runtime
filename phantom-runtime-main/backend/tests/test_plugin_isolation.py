"""Plugin routes must be tenant-scoped like the state/event routes: no unauthenticated reads, no
running another tenant's plugin, no running a plugin on another tenant's entity."""
import uuid

from .conftest import mint_key, eid

CODE = 'result={"n": len(state)}'


def _two_tenants(client, admin_key, workspace):
    ws2 = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    return (mint_key(client, admin_key, workspace["id"], name="a"), mint_key(client, admin_key, ws2["id"], name="b"),
            workspace["id"], ws2["id"])


def _plugin(client, admin_key, workspace_id):
    r = client.post("/api/plugins/", json={"name": "p", "code": CODE, "workspace_id": workspace_id},
                    headers={"X-API-Key": admin_key})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _entity(client, key):
    e = eid()
    assert client.post("/api/events/", json={"entity_id": e, "event_type": "init", "payload": {"x": 1}},
                       headers={"X-API-Key": key}).status_code == 200
    return e


def test_plugin_executions_requires_auth(client, admin_key, workspace):
    pid = _plugin(client, admin_key, workspace["id"])
    assert client.get(f"/api/plugins/{pid}/executions").status_code == 401


def test_own_plugin_on_own_entity_works(client, admin_key, workspace):
    key_a, _, ws_a, _ = _two_tenants(client, admin_key, workspace)
    pid, entity = _plugin(client, admin_key, ws_a), _entity(client, key_a)
    r = client.post(f"/api/plugins/{pid}/execute", json={"entity_id": entity}, headers={"X-API-Key": key_a})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == {"n": 1}
    ex = client.get(f"/api/plugins/{pid}/executions", headers={"X-API-Key": key_a})
    assert ex.status_code == 200 and len(ex.json()["executions"]) == 1


def test_cannot_execute_another_tenants_plugin(client, admin_key, workspace):
    key_a, key_b, ws_a, _ = _two_tenants(client, admin_key, workspace)
    pid_a = _plugin(client, admin_key, ws_a)
    entity_b = _entity(client, key_b)
    r = client.post(f"/api/plugins/{pid_a}/execute", json={"entity_id": entity_b}, headers={"X-API-Key": key_b})
    assert r.status_code == 404


def test_cannot_run_a_plugin_on_another_tenants_entity(client, admin_key, workspace):
    key_a, key_b, _, ws_b = _two_tenants(client, admin_key, workspace)
    pid_b, entity_a = _plugin(client, admin_key, ws_b), _entity(client, key_a)
    r = client.post(f"/api/plugins/{pid_b}/execute", json={"entity_id": entity_a}, headers={"X-API-Key": key_b})
    assert r.status_code == 404


def test_cannot_read_another_tenants_plugin_executions(client, admin_key, workspace):
    key_a, key_b, ws_a, _ = _two_tenants(client, admin_key, workspace)
    pid_a, entity_a = _plugin(client, admin_key, ws_a), _entity(client, key_a)
    assert client.post(f"/api/plugins/{pid_a}/execute", json={"entity_id": entity_a},
                       headers={"X-API-Key": key_a}).status_code == 200
    assert client.get(f"/api/plugins/{pid_a}/executions", headers={"X-API-Key": key_b}).status_code == 404


def test_unknown_or_malformed_plugin_id_is_404_not_500(client, admin_key, workspace):
    key_a, _, _, _ = _two_tenants(client, admin_key, workspace)
    for pid in (str(uuid.uuid4()), "not-a-uuid"):
        r = client.post(f"/api/plugins/{pid}/execute", json={"entity_id": eid()}, headers={"X-API-Key": key_a})
        assert r.status_code == 404, (pid, r.status_code)


def test_plugin_workspace_defaults_to_the_callers_tenant(client, admin_key, workspace):
    r = client.post("/api/plugins/", json={"name": "p", "code": CODE}, headers={"X-API-Key": admin_key})
    assert r.status_code == 200
    from app.core.database import SessionLocal
    from app.core.models_v2 import Plugin
    db = SessionLocal()
    try:
        assert str(db.query(Plugin).filter(Plugin.id == r.json()["id"]).one().workspace_id) == workspace["id"]
    finally:
        db.close()


# ---- strategies (v3) are tenant-scoped the same way ----

def _tenant_admin(client, admin_key, workspace_id):
    return mint_key(client, admin_key, workspace_id, role="admin", name="tenant-admin")


def _strategy(client, key, code='result={"n": len(events)}'):
    r = client.post("/api/v3/strategies", json={"name": "s", "strategy_type": "custom", "code": code},
                    headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _v3_event(client, key, entity, payload):
    assert client.post("/api/v3/events", json={"entity_id": entity, "event_type": "init", "payload": payload},
                       headers={"X-API-Key": key}).status_code == 200


def test_strategy_sees_only_its_own_tenants_events_on_a_shared_entity_id(client, admin_key, workspace):
    key_a, key_b, _, ws_b = _two_tenants(client, admin_key, workspace)
    entity = eid()
    _v3_event(client, key_a, entity, {"secret": "A"})
    _v3_event(client, key_a, entity, {"secret": "A2"})
    sid_b = _strategy(client, _tenant_admin(client, admin_key, ws_b))
    r = client.post(f"/api/v3/strategies/{sid_b}/execute", params={"entity_id": entity, "emit_events": False},
                    headers={"X-API-Key": key_b})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == {"n": 0}  # B sees none of A's events


def test_cannot_execute_another_tenants_strategy(client, admin_key, workspace):
    key_a, key_b, ws_a, _ = _two_tenants(client, admin_key, workspace)
    sid_a = _strategy(client, _tenant_admin(client, admin_key, ws_a))
    r = client.post(f"/api/v3/strategies/{sid_a}/execute", params={"entity_id": eid()}, headers={"X-API-Key": key_b})
    assert r.status_code == 404


def test_strategy_output_event_belongs_to_the_callers_tenant(client, admin_key, workspace):
    key_a, key_b, ws_a, _ = _two_tenants(client, admin_key, workspace)
    entity = eid()
    _v3_event(client, key_a, entity, {"x": 1})
    sid = _strategy(client, _tenant_admin(client, admin_key, ws_a), 'result={"seen": len(events)}')
    r = client.post(f"/api/v3/strategies/{sid}/execute", params={"entity_id": entity}, headers={"X-API-Key": key_a})
    assert r.status_code == 200 and r.json()["output_events"]
    chain_a = client.get(f"/api/v3/events/chain/{entity}", headers={"X-API-Key": key_a}).json()
    assert chain_a["chain_length"] == 2
    assert chain_a["events"][-1]["event_type"] == "strategy_custom"
    assert client.get(f"/api/v3/events/chain/{entity}", headers={"X-API-Key": key_b}).json()["chain_length"] == 0


def test_unknown_or_malformed_strategy_id_is_404(client, admin_key, workspace):
    key_a, _, _, _ = _two_tenants(client, admin_key, workspace)
    for sid in (str(uuid.uuid4()), "not-a-uuid"):
        r = client.post(f"/api/v3/strategies/{sid}/execute", params={"entity_id": eid()}, headers={"X-API-Key": key_a})
        assert r.status_code == 404, (sid, r.status_code)
