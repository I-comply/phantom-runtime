"""POST /api/workspaces/ needs the bootstrap key or a platform admin key (it used to be open to anyone)."""
import os
import uuid

from .conftest import make_ws, mint_key


def _body(**kw):
    return dict({"name": f"ws-{uuid.uuid4().hex[:8]}"}, **kw)


def test_anonymous_cannot_create_a_workspace(client):
    assert client.post("/api/workspaces/", json=_body()).status_code == 401


def test_wrong_bootstrap_key_is_rejected(client):
    assert client.post("/api/workspaces/", json=_body(), headers={"X-Bootstrap-Key": "nope"}).status_code == 401


def test_a_workspace_key_cannot_create_more_workspaces(client, workspace):
    r = client.post("/api/workspaces/", json=_body(), headers={"X-API-Key": workspace["api_key"]})
    assert r.status_code == 401  # pk_ workspace keys are not API keys


def test_a_workspace_admin_cannot_create_workspaces(client, workspace):
    admin = mint_key(client, None, workspace["id"], role="admin")
    assert client.post("/api/workspaces/", json=_body(), headers={"X-API-Key": admin}).status_code == 403


def test_a_platform_admin_can_create_workspaces(client, platform_key):
    r = client.post("/api/workspaces/", json=_body(), headers={"X-API-Key": platform_key})
    assert r.status_code == 201 and r.json()["api_key"].startswith("pk_")


def test_bootstrap_key_can_create_workspaces(client):
    assert make_ws(client)["api_key"].startswith("pk_")


def test_unconfigured_bootstrap_key_cannot_be_matched_by_an_empty_header(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_KEY", "")
    assert client.post("/api/workspaces/", json=_body(), headers={"X-Bootstrap-Key": ""}).status_code == 401


def test_settings_size_and_name_are_validated(client):
    h = {"X-Bootstrap-Key": os.environ["PHANTOM_BOOTSTRAP_ADMIN_KEY"]}
    assert client.post("/api/workspaces/", json=_body(settings={"blob": "x" * 9000}), headers=h).status_code == 422
    assert client.post("/api/workspaces/", json={"name": ""}, headers=h).status_code == 422
    assert client.post("/api/workspaces/", json={"name": "n" * 121}, headers=h).status_code == 422
    assert client.post("/api/workspaces/", json=_body(settings={"tier": "free", "features": ["a"]}), headers=h).status_code == 201
