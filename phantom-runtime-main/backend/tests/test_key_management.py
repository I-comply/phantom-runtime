"""API key lifecycle: expiry at creation, list, revoke, rotate; all tenant-scoped."""
from .conftest import make_ws, mint_key, eid

K = "/api/v3/security/api-keys"


def _create(client, key, tenant, **extra):
    return client.post(K, json={"tenant_id": tenant, "role": "agent", "name": "k", **extra}, headers={"X-API-Key": key})


def _ok(client, key):
    return client.get("/api/events/", headers={"X-API-Key": key}).status_code


def test_key_with_expiry_works_until_it_expires(client, admin_key, workspace):
    r = _create(client, admin_key, workspace["id"], expires_in_days=1)
    assert r.status_code == 200, r.text
    assert _ok(client, r.json()["key"]) == 200
    assert r.json()["expires_at"]


def test_expires_in_days_validated(client, admin_key, workspace):
    for bad in (0, -1, 4000):
        assert _create(client, admin_key, workspace["id"], expires_in_days=bad).status_code == 422


def test_expired_key_is_rejected_not_500(client, admin_key, workspace):
    from datetime import datetime, timedelta
    from app.core.database import SessionLocal
    from app.core.models_v3 import APIKey
    r = _create(client, admin_key, workspace["id"], expires_in_days=1)
    kid, key = r.json()["id"], r.json()["key"]
    db = SessionLocal()
    try:
        db.query(APIKey).filter(APIKey.id == kid).update({"expires_at": datetime.utcnow() - timedelta(minutes=1)})
        db.commit()
    finally:
        db.close()
    assert _ok(client, key) == 401


def test_list_keys_scoped_and_without_secrets(client, admin_key, workspace):
    other = make_ws(client, "o")
    mint_key(client, admin_key, other["id"], name="other-ws")
    mine = mint_key(client, admin_key, workspace["id"], name="mine")
    rows = client.get(K, headers={"X-API-Key": admin_key}).json()
    names = {x["name"] for x in rows}
    assert "mine" in names and "other-ws" not in names
    for x in rows:
        assert "key" not in x and "key_hash" not in x
        assert set(x) >= {"id", "name", "role", "is_active", "created_at", "expires_at", "last_used_at"}
    assert client.get(K, headers={"X-API-Key": mine}).status_code == 403


def test_revoke_key(client, admin_key, workspace):
    r = _create(client, admin_key, workspace["id"])
    kid, key = r.json()["id"], r.json()["key"]
    assert _ok(client, key) == 200
    assert client.post(f"{K}/{kid}/revoke", headers={"X-API-Key": admin_key}).status_code == 200
    assert _ok(client, key) == 401
    listed = {x["id"]: x for x in client.get(K, headers={"X-API-Key": admin_key}).json()}
    assert listed[kid]["is_active"] is False


def test_revoke_other_workspaces_key_is_404(client, admin_key, workspace):
    other = make_ws(client, "o")
    r = client.post(K, json={"tenant_id": other["id"], "role": "agent", "name": "x"},
                    headers={"X-Bootstrap-Key": "ci-test-bootstrap-key"})
    kid, key = r.json()["id"], r.json()["key"]
    assert client.post(f"{K}/{kid}/revoke", headers={"X-API-Key": admin_key}).status_code == 404
    assert _ok(client, key) == 200


def test_rotate_key(client, admin_key, workspace):
    r = _create(client, admin_key, workspace["id"])
    kid, old = r.json()["id"], r.json()["key"]
    rot = client.post(f"{K}/{kid}/rotate", headers={"X-API-Key": admin_key})
    assert rot.status_code == 200, rot.text
    new = rot.json()["key"]
    assert new != old and rot.json()["id"] != kid and rot.json()["role"] == "agent"
    assert _ok(client, old) == 401
    assert _ok(client, new) == 200
    assert client.post(f"{K}/{kid}/rotate", headers={"X-API-Key": admin_key}).status_code == 409  # already revoked


def test_unknown_key_id_404(client, admin_key):
    import uuid
    assert client.post(f"{K}/{uuid.uuid4()}/revoke", headers={"X-API-Key": admin_key}).status_code == 404
    assert client.post(f"{K}/not-a-uuid/revoke", headers={"X-API-Key": admin_key}).status_code == 404
