"""An entity belongs to the workspace that first wrote it. Other workspaces must not append to it
(v1 or v3), and v3 chains are tenant-aware."""
from .conftest import make_ws, mint_key, eid


def _setup(client, admin_key):
    a, b = make_ws(client, "a"), make_ws(client, "b")
    return a, b, mint_key(client, admin_key, a["id"]), mint_key(client, admin_key, b["id"])


def test_v1_write_to_other_tenants_entity_rejected(client, admin_key):
    a, b, ka, kb = _setup(client, admin_key)
    e = eid()
    assert client.post("/api/events/", json={"entity_id": e, "event_type": "deposit", "payload": {"asset": "USD", "amount": "5"}},
                       headers={"X-API-Key": ka}).status_code == 200
    r = client.post("/api/events/", json={"entity_id": e, "event_type": "deposit", "payload": {"asset": "USD", "amount": "999"}},
                    headers={"X-API-Key": kb})
    assert r.status_code == 409, r.text
    events = client.get(f"/api/events/entity/{e}", headers={"X-API-Key": ka}).json()
    assert len(events) == 1


def test_v3_write_to_other_tenants_chain_rejected(client, admin_key):
    a, b, ka, kb = _setup(client, admin_key)
    e = eid()
    assert client.post("/api/v3/events", json={"entity_id": e, "event_type": "x", "payload": {"n": 1}},
                       headers={"X-API-Key": ka}).status_code == 200
    r = client.post("/api/v3/events", json={"entity_id": e, "event_type": "x", "payload": {"n": 2}},
                    headers={"X-API-Key": kb})
    assert r.status_code == 409, r.text
    chain = client.get(f"/api/v3/events/chain/{e}", headers={"X-API-Key": ka}).json()["events"]
    assert len(chain) == 1


def test_v1_and_v3_same_tenant_still_work(client, admin_key):
    a, b, ka, kb = _setup(client, admin_key)
    e = eid()
    for n in (1, 2):
        assert client.post("/api/v3/events", json={"entity_id": e, "event_type": "x", "payload": {"n": n}},
                           headers={"X-API-Key": ka}).status_code == 200
    assert client.get(f"/api/v3/events/chain/{e}", headers={"X-API-Key": ka}).json()["chain_length"] == 2
