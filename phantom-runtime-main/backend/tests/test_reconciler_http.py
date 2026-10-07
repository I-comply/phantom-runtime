"""Two real HTTP nodes: the client talks to the FastAPI routes over a socket."""
import asyncio
import threading

import pytest
import uvicorn
from fastapi import FastAPI

from app.api import routes_reconciler
from app.core.config import settings
from app.core.reconciler import GCounter, ReconciliationDaemon, ReplicaState
from app.core.reconciler_http import HttpPeer, parse_peers, token_valid


@pytest.fixture
def node(monkeypatch):
    monkeypatch.setattr(settings, "RECONCILER_ENABLED", True)
    monkeypatch.setattr(settings, "RECONCILER_SHARED_SECRET", "s3cret")
    state = ReplicaState("b")
    state.update("hits", GCounter({"b": 7}))
    app = FastAPI()
    app.state.replica_state = state
    app.include_router(routes_reconciler.router)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        pass
    port = server.servers[0].sockets[0].getsockname()[1]
    yield state, f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def test_token_and_peer_parsing():
    assert token_valid("a", "a") and not token_valid("a", "b") and not token_valid(None, "a") and not token_valid("a", None)
    assert parse_peers("b=http://x:1/, c=https://y") == {"b": "http://x:1", "c": "https://y"}
    with pytest.raises(ValueError):
        parse_peers("b=ftp://x")


def test_http_reconcile_and_auth(node):
    remote, url = node

    async def go():
        with pytest.raises(Exception):
            await HttpPeer("b", url, "wrong").digest()
        local = ReplicaState("a")
        d = ReconciliationDaemon(local, [HttpPeer("b", url, "s3cret")], timeout=2)
        rep = await d.reconcile_once()
        assert rep.drifted == {"b"} and rep.merged == {"b"}
        assert local.digest() == remote.digest()
        assert (await d.reconcile_once()).drifted == set()
    asyncio.run(go())


def test_endpoints_hidden_when_disabled(node, monkeypatch):
    _, url = node
    monkeypatch.setattr(settings, "RECONCILER_ENABLED", False)

    async def go():
        with pytest.raises(Exception):
            await HttpPeer("b", url, "s3cret").digest()
    asyncio.run(go())
