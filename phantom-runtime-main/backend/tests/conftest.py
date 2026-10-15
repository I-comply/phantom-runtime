import os
import sys
import uuid
import pytest

# Required before importing app.main (it reads these at import time via
# app.core.config.settings). Tests never rely on a real bootstrap secret being
# kept private — this is a throwaway value for the test DB only.
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("PHANTOM_BOOTSTRAP_ADMIN_KEY", "ci-test-bootstrap-key")
os.environ.setdefault("SANDBOX_EXECUTOR", "subprocess")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def bootstrap_key():
    return os.environ["PHANTOM_BOOTSTRAP_ADMIN_KEY"]


def make_ws(client, prefix="ws"):
    """Create a workspace. Creation needs the bootstrap key (or a platform admin key)."""
    r = client.post("/api/workspaces/", json={"name": f"{prefix}-{uuid.uuid4().hex[:8]}"},
                    headers={"X-Bootstrap-Key": os.environ["PHANTOM_BOOTSTRAP_ADMIN_KEY"]})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def workspace(client):
    """A fresh workspace per test, so tests never collide on shared state."""
    return make_ws(client)


@pytest.fixture
def admin_key(client, bootstrap_key, workspace):
    """A fresh admin-role API key, in a fresh workspace, per test."""
    r = client.post(
        "/api/v3/security/api-keys",
        json={"tenant_id": workspace["id"], "role": "admin", "name": "admin"},
        headers={"X-Bootstrap-Key": bootstrap_key},
    )
    assert r.status_code == 200, r.text
    return r.json()["key"]


@pytest.fixture
def platform_key(client, bootstrap_key, monkeypatch):
    """An admin key in a dedicated platform workspace, which PHANTOM_PLATFORM_TENANT_ID names for the
    duration of the test. Only this key (not a per-workspace admin) sees across tenants."""
    ws = make_ws(client, "platform")
    r = client.post(
        "/api/v3/security/api-keys",
        json={"tenant_id": ws["id"], "role": "admin", "name": "platform"},
        headers={"X-Bootstrap-Key": bootstrap_key},
    )
    assert r.status_code == 200, r.text
    monkeypatch.setenv("PHANTOM_PLATFORM_TENANT_ID", ws["id"])
    return r.json()["key"]


def mint_key(client, admin_key, workspace_id, role="agent", name=None):
    """Mint a key for any workspace with the bootstrap key (a per-workspace admin key can only mint
    for its own workspace). `admin_key` is accepted for call-site compatibility and ignored."""
    r = client.post(
        "/api/v3/security/api-keys",
        json={"tenant_id": workspace_id, "role": role, "name": name or f"{role}-{uuid.uuid4().hex[:6]}"},
        headers={"X-Bootstrap-Key": os.environ["PHANTOM_BOOTSTRAP_ADMIN_KEY"]},
    )
    assert r.status_code == 200, r.text
    return r.json()["key"]


def eid():
    """A unique entity_id, so tests never collide on shared state."""
    return f"e-{uuid.uuid4().hex[:10]}"
