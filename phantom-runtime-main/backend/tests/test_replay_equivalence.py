"""Replay integrity on the production classes (not mocks): one reconstructor, deterministic replay,
snapshot + incremental == full replay for every event type, id-based ordering, and the
snapshot-vs-concurrent-writer race. Needs the same Postgres the other backend tests use."""
import copy
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import SessionLocal
from app.core.event_store import EventStore
from app.core.models import Event
from app.core.models_v2 import Snapshot
from app.core.reconstructor import StateReconstructor
from app.core.reconstructor_v2 import StateReconstructorV2
from app.core.snapshot_manager import SnapshotManager
from .conftest import eid

SEQUENCE = [
    ("init", {"owner": "a", "nested": {"k": [1, 2]}}),
    ("update", {"owner": "b", "extra": {"x": 1}}),
    ("deposit", {"asset": "USD", "amount": 100}),
    ("withdraw", {"asset": "USD", "amount": 30}),
    ("trade", {"from_asset": "USD", "to_asset": "BTC", "from_amount": 10, "to_amount": 0.001}),
    ("transfer", {"asset": "BTC", "amount": 0.0005, "to": "x"}),
    ("stake", {"asset": "BTC", "amount": 0.0002}),
    ("unstake", {"asset": "BTC", "amount": 0.0002}),
    ("compute", {"score": 7}),
    ("delete_field", {"field": "extra"}),
    ("custom_type", {"misc": True}),
    ("reset", {}),
    ("init", {"owner": "c"}),
    ("deposit", {"asset": "ETH", "amount": 2}),
]


@pytest.fixture
def db(client):  # `client` startup creates the tables
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def append(db, entity, events):
    return [EventStore.append_event(db, entity, t, copy.deepcopy(p)) for t, p in events]


def full_replay(db, entity):
    evs = db.query(Event).filter(Event.entity_id == entity).order_by(Event.id.asc()).all()
    return StateReconstructorV2.reconstruct(evs)


def test_one_reconstructor_for_every_path():
    # v1 and V2 used to disagree for the same events (v1: {'asset','amount'}, V2: balances + history)
    evs = [Event(entity_id="x", event_type=t, payload=copy.deepcopy(p)) for t, p in SEQUENCE]
    assert StateReconstructor.reconstruct(evs) == StateReconstructorV2.reconstruct(evs)
    assert callable(StateReconstructorV2.apply_event)


def test_replay_is_deterministic_and_does_not_mutate_events():
    evs = [Event(entity_id="x", event_type=t, payload=copy.deepcopy(p)) for t, p in SEQUENCE]
    before = [copy.deepcopy(e.payload) for e in evs]
    a = StateReconstructorV2.reconstruct(evs)
    b = StateReconstructorV2.reconstruct(evs)
    assert a == b
    assert [e.payload for e in evs] == before  # replay must not write through into event payloads


def test_state_does_not_alias_event_payloads():
    ev = Event(entity_id="x", event_type="init", payload={"balances": {"USD": 1}, "nested": {"k": [1]}})
    state = StateReconstructorV2.reconstruct([ev])
    state["balances"]["USD"] = 999
    state["nested"]["k"].append(2)
    assert ev.payload == {"balances": {"USD": 1}, "nested": {"k": [1]}}


@pytest.mark.parametrize("cut", range(1, len(SEQUENCE)))
def test_snapshot_plus_incremental_equals_full_replay(db, cut):
    entity = eid()
    append(db, entity, SEQUENCE[:cut])
    snap = SnapshotManager.create_snapshot(db, entity)
    assert snap is not None and snap.event_count == cut
    append(db, entity, SEQUENCE[cut:])
    assert SnapshotManager.reconstruct_with_snapshot(db, entity) == full_replay(db, entity)


def test_reconstruct_with_snapshot_does_not_modify_the_stored_snapshot(db):
    entity = eid()
    append(db, entity, SEQUENCE[:5])
    snap = SnapshotManager.create_snapshot(db, entity)
    stored = copy.deepcopy(snap.state_data)
    append(db, entity, SEQUENCE[5:])
    SnapshotManager.reconstruct_with_snapshot(db, entity)
    db.refresh(snap)
    assert snap.state_data == stored


def test_events_are_ordered_by_id_not_by_created_at(db):
    # created_at is set in Python at construction, so it can disagree with commit (id) order
    entity = eid()
    base = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, (t, p) in enumerate(SEQUENCE[:6]):
        db.add(Event(entity_id=entity, event_type=t, payload=copy.deepcopy(p), created_at=base - timedelta(minutes=i)))
        db.commit()
    by_id = db.query(Event).filter(Event.entity_id == entity).order_by(Event.id.asc()).all()
    expected = StateReconstructorV2.reconstruct(by_id)
    assert StateReconstructorV2.reconstruct(EventStore.get_events(db, entity)) == expected
    snap = SnapshotManager.create_snapshot(db, entity)
    assert snap.state_data == expected
    assert SnapshotManager.reconstruct_with_snapshot(db, entity) == expected


def test_snapshot_waits_for_in_flight_writer_so_no_event_is_skipped(db):
    """A snapshot must never be cut while a lower-id event is still uncommitted: the later
    `id > last_event_id` filter would skip it forever."""
    entity = eid()
    append(db, entity, SEQUENCE[:3])
    writer = SessionLocal()
    try:
        EventStore.lock_entity(writer, entity)
        late = Event(entity_id=entity, event_type="update", payload={"late": True})
        writer.add(late)
        writer.flush()  # id allocated, not committed

        done = {}

        def other_writer():
            s = SessionLocal()
            try:
                done["event"] = EventStore.append_event(s, entity, "update", {"after": True})
            finally:
                s.close()

        def snapshotter():
            s = SessionLocal()
            try:
                done["snap"] = SnapshotManager.create_snapshot(s, entity)
            finally:
                s.close()

        threads = [threading.Thread(target=other_writer), threading.Thread(target=snapshotter)]
        for t in threads:
            t.start()
        time.sleep(1.0)
        assert all(t.is_alive() for t in threads), "writers/snapshots must wait for the in-flight writer"
        writer.commit()
        for t in threads:
            t.join(timeout=20)
            assert not t.is_alive()
    finally:
        writer.close()

    db.expire_all()
    state = SnapshotManager.reconstruct_with_snapshot(db, entity)
    assert state == full_replay(db, entity)
    assert state["late"] is True and state["after"] is True


def test_concurrent_writers_and_snapshots_converge(db):
    entity = eid()
    append(db, entity, SEQUENCE[:2])
    stop = threading.Event()
    errors = []

    def writer(n):
        s = SessionLocal()
        try:
            for i in range(15):
                EventStore.append_event(s, entity, "update", {f"w{n}_{i}": i})
        except Exception as e:  # pragma: no cover
            errors.append(e)
        finally:
            s.close()

    def snapshotter():
        s = SessionLocal()
        try:
            while not stop.is_set():
                SnapshotManager.create_snapshot(s, entity)
                time.sleep(0.01)
        except Exception as e:  # pragma: no cover
            errors.append(e)
        finally:
            s.close()

    ws = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    sn = threading.Thread(target=snapshotter)
    sn.start()
    [w.start() for w in ws]
    [w.join(timeout=60) for w in ws]
    stop.set()
    sn.join(timeout=20)
    assert not errors
    db.expire_all()
    expected = full_replay(db, entity)
    assert len([k for k in expected if k.startswith("w")]) == 60
    assert SnapshotManager.reconstruct_with_snapshot(db, entity) == expected


def test_rebuild_snapshots_repairs_a_legacy_snapshot(db):
    entity = eid()
    append(db, entity, SEQUENCE[:4])
    snap = SnapshotManager.create_snapshot(db, entity)
    # simulate a snapshot written by the old v1 reconstructor (deposit/withdraw collapsed into the payload)
    snap.state_data = {"owner": "b", "asset": "USD", "amount": 30}
    db.commit()
    append(db, entity, SEQUENCE[4:])
    changed = SnapshotManager.rebuild_snapshots(db, entity_id=entity)
    assert changed == 1
    db.expire_all()
    assert SnapshotManager.reconstruct_with_snapshot(db, entity) == full_replay(db, entity)
    assert SnapshotManager.rebuild_snapshots(db, entity_id=entity) == 0  # idempotent
