"""The async v3 pipeline: queued events keep their tenant, processing is tenant-scoped, and items
stuck in 'processing' or failed are recovered instead of being lost."""
import uuid
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.core.event_engine_v3 import AsyncEventPipeline, EventEngineV3
from app.core.models_v3 import EventQueue, EventV3
from .conftest import mint_key, eid


def _tenants(client, admin_key, workspace):
    ws2 = client.post("/api/workspaces/", json={"name": f"ws-{uuid.uuid4().hex[:8]}"}).json()
    return mint_key(client, admin_key, workspace["id"], name="a"), mint_key(client, admin_key, ws2["id"], name="b")


def _queue(client, key, entity, payload=None):
    r = client.post("/api/v3/events/queue", json={"entity_id": entity, "event_type": "init", "payload": payload or {"x": 1}},
                    headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    return r.json()["queue_id"]


def _chain(client, key, entity):
    return client.get(f"/api/v3/events/chain/{entity}", headers={"X-API-Key": key}).json()["chain_length"]


def test_queued_event_belongs_to_the_tenant_that_queued_it(client, admin_key, workspace):
    key_a, key_b = _tenants(client, admin_key, workspace)
    entity = eid()
    _queue(client, key_a, entity)
    r = client.post("/api/v3/events/process-queue", headers={"X-API-Key": key_a})
    assert r.json()["processed_count"] == 1
    assert _chain(client, key_a, entity) == 1       # visible to its writer (used to be 0)
    assert _chain(client, key_b, entity) == 0       # not to another tenant
    assert _chain(client, admin_key, entity) >= 1


def test_process_queue_only_touches_the_callers_tenant(client, admin_key, workspace):
    key_a, key_b = _tenants(client, admin_key, workspace)
    entity = eid()
    qid = _queue(client, key_a, entity)
    assert client.post("/api/v3/events/process-queue", headers={"X-API-Key": key_b}).json()["processed_count"] == 0
    db = SessionLocal()
    try:
        assert db.query(EventQueue).filter(EventQueue.id == qid).one().status == "pending"
    finally:
        db.close()
    assert client.post("/api/v3/events/process-queue", headers={"X-API-Key": key_a}).json()["processed_count"] == 1


def test_platform_admin_processes_every_tenants_queue(client, admin_key, workspace, platform_key):
    key_a, key_b = _tenants(client, admin_key, workspace)
    ea, eb = eid(), eid()
    _queue(client, key_a, ea)
    _queue(client, key_b, eb)
    assert client.post("/api/v3/events/process-queue", headers={"X-API-Key": platform_key}).json()["processed_count"] >= 2
    assert _chain(client, key_a, ea) == 1 and _chain(client, key_b, eb) == 1


def test_stale_processing_item_is_recovered_without_duplicating_the_event(client, admin_key, workspace):
    key_a, _ = _tenants(client, admin_key, workspace)
    entity, qid = eid(), None
    db = SessionLocal()
    try:
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        # crashed after the event was written but before the item was marked completed
        done = EventQueue(entity_id=entity, status="processing",
                          event_data={"event_type": "init", "payload": {"a": 1}, "tenant_id": workspace["id"], "_claimed_at": old})
        db.add(done)
        db.commit()
        EventEngineV3.create_event(db, entity, "init", {"a": 1}, tenant_id=workspace["id"], created_by=f"queue:{done.id}")
        # crashed before the event was written
        entity2 = eid()
        lost = EventQueue(entity_id=entity2, status="processing",
                          event_data={"event_type": "init", "payload": {"b": 1}, "tenant_id": workspace["id"], "_claimed_at": old})
        db.add(lost)
        db.commit()
        done_id, lost_id = done.id, lost.id
    finally:
        db.close()
    client.post("/api/v3/events/process-queue", headers={"X-API-Key": admin_key})
    db = SessionLocal()
    try:
        assert db.query(EventQueue).filter(EventQueue.id == done_id).one().status == "completed"
        assert db.query(EventQueue).filter(EventQueue.id == lost_id).one().status == "completed"
        assert db.query(EventV3).filter(EventV3.entity_id == entity).count() == 1   # not written twice
        assert db.query(EventV3).filter(EventV3.entity_id == entity2).count() == 1  # written once, not lost
    finally:
        db.close()


def test_fresh_processing_item_is_left_alone(client, admin_key, workspace):
    entity = eid()
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).isoformat()
        item = EventQueue(entity_id=entity, status="processing",
                          event_data={"event_type": "init", "payload": {}, "tenant_id": workspace["id"], "_claimed_at": now})
        db.add(item)
        db.commit()
        iid = item.id
    finally:
        db.close()
    client.post("/api/v3/events/process-queue", headers={"X-API-Key": admin_key})
    db = SessionLocal()
    try:
        assert db.query(EventQueue).filter(EventQueue.id == iid).one().status == "processing"
    finally:
        db.close()


def test_failed_items_are_retried_then_marked_failed_and_do_not_block_the_batch(client, admin_key, workspace):
    good_entity = eid()
    db = SessionLocal()
    try:
        bad = EventQueue(entity_id=eid(), event_data={"payload": {}, "tenant_id": workspace["id"]})  # no event_type
        db.add(bad)
        db.commit()
        bad_id = bad.id
    finally:
        db.close()
    qkey = mint_key(client, admin_key, workspace["id"], name="q")
    _queue(client, qkey, good_entity)
    for _ in range(AsyncEventPipeline.MAX_RETRIES + 1):
        client.post("/api/v3/events/process-queue", headers={"X-API-Key": admin_key})
    db = SessionLocal()
    try:
        item = db.query(EventQueue).filter(EventQueue.id == bad_id).one()
        assert (item.status, item.retry_count) == ("failed", AsyncEventPipeline.MAX_RETRIES)
        assert db.query(EventV3).filter(EventV3.entity_id == good_entity).count() == 1
    finally:
        db.close()
