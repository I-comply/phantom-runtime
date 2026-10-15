"""Multi-worker safety: shared event fan-out (LISTEN/NOTIFY), single reconciler leader, snapshots off the read path."""
import asyncio
import threading
import time
import uuid

import pytest

from app.core.config import settings
from app.core.event_bus import EventBus, encode, MAX_PAYLOAD_BYTES
from app.reconciler.leader import LeaderElector
from .conftest import eid

pytestmark = pytest.mark.skipif(not settings.DATABASE_URL.startswith("postgres"), reason="needs PostgreSQL")


def _wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_event_reaches_every_worker():
    """Two buses = two worker processes' listeners: an event published on one is delivered on both."""
    got = {"a": [], "b": []}
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    buses = {}
    for name in got:
        async def deliver(msg, tenant, name=name):
            got[name].append((tenant, msg["n"]))
        buses[name] = EventBus(settings.DATABASE_URL)
        buses[name].start(loop, deliver)
    try:
        for n in range(5):
            buses["a"].publish({"n": n}, "t1")
        assert _wait(lambda: len(got["a"]) == 5 and len(got["b"]) == 5)
        assert got["a"] == got["b"] == [("t1", n) for n in range(5)]  # same order everywhere
    finally:
        for b in buses.values():
            b.stop()
        loop.call_soon_threadsafe(loop.stop)


def test_oversize_payload_is_reduced_to_ids():
    msg = {"type": "new_event", "data": {"id": 1, "entity_id": "e", "event_type": "x", "blob": "z" * 20000}}
    raw = encode(msg, "t")
    assert len(raw.encode()) <= MAX_PAYLOAD_BYTES and '"id": 1' in raw and "blob" not in raw


def test_http_write_is_pushed_through_the_bus(client, admin_key, workspace):
    with client.websocket_connect("/ws/events") as ws:
        ws.send_json({"type": "auth", "api_key": admin_key})
        assert ws.receive_json()["type"] == "auth_ok"
        e = eid()
        assert client.post("/api/events/", json={"entity_id": e, "event_type": "init", "payload": {"x": 1}},
                           headers={"X-API-Key": admin_key}).status_code == 200
        msg = ws.receive_json()
        assert msg["type"] == "new_event" and msg["data"]["entity_id"] == e


def test_only_one_leader_and_failover():
    key = uuid.uuid4().int & 0x7FFFFFFFFFFFFFFF
    events = []
    electors = []
    for name in ("a", "b"):
        electors.append(LeaderElector(settings.DATABASE_URL, lambda n=name: events.append(("up", n)),
                                      lambda n=name: events.append(("down", n)),
                                      retry_s=0.05, heartbeat_s=0.05, lock_key=key))
    a, b = electors
    a.start()
    assert _wait(lambda: a.is_leader)
    b.start()
    time.sleep(0.4)
    assert a.is_leader and not b.is_leader
    a.stop()
    assert _wait(lambda: b.is_leader)
    assert [e for e in events if e[0] == "up"] == [("up", "a"), ("up", "b")]
    b.stop()


def test_concurrent_snapshot_if_due_creates_one(client, admin_key, workspace, monkeypatch):
    from app.core.database import SessionLocal
    from app.core.models_v2 import Snapshot
    from app.core.snapshot_manager import SnapshotManager
    monkeypatch.setattr(SnapshotManager, "SNAPSHOT_INTERVAL", 5)
    e = eid()
    for i in range(6):
        assert client.post("/api/events/", json={"entity_id": e, "event_type": "init" if i == 0 else "update",
                                                 "payload": {"i": i}},
                           headers={"X-API-Key": admin_key}).status_code == 200
    ts = [threading.Thread(target=SnapshotManager.snapshot_if_due, args=(e, workspace["id"])) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    db = SessionLocal()
    try:
        assert db.query(Snapshot).filter(Snapshot.entity_id == e).count() == 1
    finally:
        db.close()
    r = client.get(f"/api/state/{e}", headers={"X-API-Key": admin_key})
    assert r.status_code == 200 and r.json()["snapshot_used"] is True
