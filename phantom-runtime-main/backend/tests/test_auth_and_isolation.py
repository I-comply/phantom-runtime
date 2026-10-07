"""Formalizes the checks run by hand during the security review/hardening work
(see the repo's PR history for #9/#10): every endpoint's unauth-vs-authed
behavior, RBAC, and real tenant isolation on reads via EntityWorkspace."""
import uuid
from .conftest import mint_key, eid


# ---- bootstrap / key minting ----

def test_unauth_admin_key_mint_blocked(client, workspace):
    r = client.post("/api/v3/security/api-keys", json={"tenant_id": workspace["id"], "role": "admin", "name": "x"})
    assert r.status_code == 401


def test_wrong_bootstrap_key_blocked(client, workspace):
    r = client.post(
        "/api/v3/security/api-keys",
        json={"tenant_id": workspace["id"], "role": "admin", "name": "x"},
        headers={"X-Bootstrap-Key": "definitely-wrong"},
    )
    assert r.status_code == 401


def test_bootstrap_mint_and_admin_can_mint_more(client, bootstrap_key, workspace, admin_key):
    r = client.post(
        "/api/v3/security/api-keys",
        json={"tenant_id": workspace["id"], "role": "agent", "name": "agent1"},
        headers={"X-API-Key": admin_key},
    )
    assert r.status_code == 200


def test_workspace_create_returns_plaintext_key_once_only(client):
    ws = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    assert ws["api_key"].startswith("pk_")
    me = client.get("/api/workspaces/me", headers={"X-API-Key": ws["api_key"]})
    assert me.status_code == 200
    assert "api_key" not in me.json()  # never echoed back after creation


# ---- every previously-open endpoint now requires auth ----

def test_v1_event_create_requires_auth(client):
    assert client.post("/api/events/", json={"entity_id": eid(), "event_type": "t", "payload": {}}).status_code == 401


def test_v1_event_read_requires_auth(client):
    assert client.get(f"/api/events/entity/{eid()}").status_code == 401


def test_state_read_requires_auth(client):
    assert client.get(f"/api/state/{eid()}").status_code == 401


def test_agent_run_requires_auth(client):
    assert client.post("/api/state/agent/run", json={"entity_id": eid()}).status_code == 401


def test_snapshot_create_requires_auth(client):
    assert client.post("/api/snapshots/", json={"entity_id": eid()}).status_code == 401


def test_defi_create_requires_auth(client):
    body = {"entity_id": eid(), "event_type": "deposit", "asset": "BTC", "amount": "1"}
    assert client.post("/api/defi/events", json=body).status_code == 401


def test_v3_event_create_requires_auth(client):
    assert client.post("/api/v3/events", json={"entity_id": eid(), "event_type": "init", "payload": {}}).status_code == 401


def test_v3_chain_read_requires_auth(client):
    assert client.get(f"/api/v3/events/chain/{eid()}").status_code == 401


def test_strategy_create_requires_auth(client):
    assert client.post("/api/v3/strategies", json={"name": "s", "strategy_type": "arbitrage"}).status_code == 401


def test_plugin_create_requires_auth(client):
    assert client.post("/api/plugins/", json={"name": "p", "code": "result={}"}).status_code == 401


# ---- RBAC / tenant isolation: v3 events ----

def test_v3_tenant_isolation_on_shared_entity_id(client, bootstrap_key, workspace, admin_key):
    entity = eid()
    ws2 = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    key_a = mint_key(client, admin_key, workspace["id"], name="a")
    key_b = mint_key(client, admin_key, ws2["id"], name="b")

    assert client.post("/api/v3/events", json={"entity_id": entity, "event_type": "init", "payload": {"owner": "A"}},
                       headers={"X-API-Key": key_a}).status_code == 200
    assert client.post("/api/v3/events", json={"entity_id": entity, "event_type": "init", "payload": {"owner": "B"}},
                       headers={"X-API-Key": key_b}).status_code == 200

    chain_b = client.get(f"/api/v3/events/chain/{entity}", headers={"X-API-Key": key_b}).json()
    assert chain_b["chain_length"] == 1
    assert chain_b["events"][0]["payload"]["owner"] == "B"

    chain_admin = client.get(f"/api/v3/events/chain/{entity}", headers={"X-API-Key": admin_key}).json()
    assert chain_admin["chain_length"] >= 2  # admin sees across tenants


# ---- RBAC / tenant isolation: v1 events + state (via EntityWorkspace) ----

def test_v1_tenant_isolation_events_and_state(client, admin_key, workspace):
    ws2 = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    key_a = mint_key(client, admin_key, workspace["id"], name="a")
    key_b = mint_key(client, admin_key, ws2["id"], name="b")
    entity = eid()

    assert client.post("/api/events/", json={"entity_id": entity, "event_type": "t", "payload": {"x": 1}},
                       headers={"X-API-Key": key_a}).status_code == 200

    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": key_b}).status_code == 404
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": key_a}).status_code == 200
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": admin_key}).status_code == 200

    assert client.get(f"/api/state/{entity}", headers={"X-API-Key": key_b}).status_code == 404
    assert client.get(f"/api/state/{entity}", headers={"X-API-Key": key_a}).status_code == 200
    assert client.post("/api/state/agent/run", json={"entity_id": entity}, headers={"X-API-Key": key_b}).status_code == 404


def test_v1_all_events_and_all_entities_scoped_per_workspace(client, admin_key, workspace):
    ws2 = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    key_a = mint_key(client, admin_key, workspace["id"], name="a")
    key_b = mint_key(client, admin_key, ws2["id"], name="b")
    entity_a, entity_b = eid(), eid()

    client.post("/api/events/", json={"entity_id": entity_a, "event_type": "t", "payload": {}}, headers={"X-API-Key": key_a})
    client.post("/api/events/", json={"entity_id": entity_b, "event_type": "t", "payload": {}}, headers={"X-API-Key": key_b})

    all_a = client.get("/api/events/", headers={"X-API-Key": key_a}).json()
    assert not any(e["entity_id"] == entity_b for e in all_a)

    ents_a = client.get("/api/state/", headers={"X-API-Key": key_a}).json()
    assert ents_a == [entity_a]


# ---- RBAC / tenant isolation: snapshots (incl. the "no snapshot yet" replay-fallback leak) ----

def test_snapshot_tenant_isolation(client, admin_key, workspace):
    ws2 = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    key_a = mint_key(client, admin_key, workspace["id"], name="a")
    key_b = mint_key(client, admin_key, ws2["id"], name="b")
    entity = eid()

    client.post("/api/events/", json={"entity_id": entity, "event_type": "t", "payload": {}}, headers={"X-API-Key": key_a})

    # before any snapshot exists: the "full replay" fallback must not leak tenant A's state to B
    assert client.get(f"/api/snapshots/entity/{entity}/state", headers={"X-API-Key": key_b}).status_code == 404
    assert client.get(f"/api/snapshots/entity/{entity}/state", headers={"X-API-Key": key_a}).status_code == 200

    assert client.post("/api/snapshots/", json={"entity_id": entity}, headers={"X-API-Key": key_a}).status_code == 200
    assert client.get(f"/api/snapshots/entity/{entity}/latest", headers={"X-API-Key": key_b}).status_code == 404
    assert client.get(f"/api/snapshots/entity/{entity}/latest", headers={"X-API-Key": key_a}).status_code == 200
    assert client.post(f"/api/snapshots/entity/{entity}/cleanup", headers={"X-API-Key": key_b}).status_code == 404


# ---- RBAC / tenant isolation: defi, including the "created via defi only" auto-claim ----

def test_defi_tenant_isolation_and_entity_auto_claim(client, admin_key, workspace):
    ws2 = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    key_a = mint_key(client, admin_key, workspace["id"], name="a")
    key_b = mint_key(client, admin_key, ws2["id"], name="b")
    entity = eid()

    body = {"entity_id": entity, "event_type": "deposit", "asset": "BTC", "amount": "1"}
    assert client.post("/api/defi/events", json=body, headers={"X-API-Key": key_a}).status_code == 200

    assert client.get(f"/api/defi/portfolio/{entity}", headers={"X-API-Key": key_b}).json()["balances"] == {}
    assert client.get(f"/api/defi/portfolio/{entity}", headers={"X-API-Key": key_a}).json()["balances"]["BTC"] == 1.0

    # entity was never posted via /api/events — defi_manager must have claimed it anyway
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": key_a}).status_code == 200
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": key_b}).status_code == 404


# ---- entity linking must not let one tenant claim another tenant's entity ----

def test_cannot_link_another_tenants_entity_to_my_workspace(client, admin_key, workspace):
    ws2 = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    key_a = mint_key(client, admin_key, workspace["id"], name="a")
    key_b = mint_key(client, admin_key, ws2["id"], name="b")
    entity = eid()
    assert client.post("/api/events/", json={"entity_id": entity, "event_type": "init", "payload": {"secret": "A"}},
                       headers={"X-API-Key": key_a}).status_code == 200
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": key_b}).status_code == 404

    link = client.post("/api/workspaces/me/entities", json={"entity_id": entity}, headers={"X-API-Key": ws2["api_key"]})
    assert link.status_code == 409

    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": key_b}).status_code == 404
    assert client.get(f"/api/state/{entity}", headers={"X-API-Key": key_b}).status_code == 404
    assert client.get(f"/api/events/entity/{entity}", headers={"X-API-Key": key_a}).status_code == 200


def test_linking_your_own_or_an_unclaimed_entity_still_works_and_is_idempotent(client, workspace):
    entity = eid()
    for _ in range(2):
        r = client.post("/api/workspaces/me/entities", json={"entity_id": entity}, headers={"X-API-Key": workspace["api_key"]})
        assert r.status_code == 201
    assert entity in client.get("/api/workspaces/me/entities", headers={"X-API-Key": workspace["api_key"]}).json()["entities"]


def test_roles_listing_requires_auth(client):
    assert client.get("/api/v3/security/roles").status_code == 401
