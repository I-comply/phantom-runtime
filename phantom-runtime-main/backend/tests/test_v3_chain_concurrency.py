"""events_v3 chains must not fork under concurrent writers (two events with the same block_index)."""
import threading

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.core.event_engine_v3 import EventEngineV3
from app.core.models_v3 import EventV3
from .conftest import eid


def test_concurrent_writers_produce_one_linear_chain(client):
    entity, n_threads, per_thread = eid(), 6, 8
    errors = []
    barrier = threading.Barrier(n_threads)

    def writer(n):
        s = SessionLocal()
        try:
            barrier.wait()
            for i in range(per_thread):
                EventEngineV3.create_event(s, entity, "update", {"w": n, "i": i})
        except Exception as e:  # pragma: no cover
            errors.append(e)
        finally:
            s.close()

    ts = [threading.Thread(target=writer, args=(n,)) for n in range(n_threads)]
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    assert not errors, errors

    db = SessionLocal()
    try:
        chain = EventEngineV3.get_entity_chain(db, entity)
        assert [e.block_index for e in chain] == list(range(n_threads * per_thread))
        assert EventEngineV3.verify_chain_integrity(db, entity) is True
    finally:
        db.close()


def test_database_rejects_a_duplicate_block_index(client):
    entity = eid()
    db = SessionLocal()
    try:
        EventEngineV3.create_event(db, entity, "init", {"a": 1})
        db.add(EventV3(entity_id=entity, event_type="fork", payload={"b": 2}, event_hash="f" * 64,
                       previous_hash=None, block_index=0))
        with pytest.raises(Exception) as exc:
            db.commit()
        assert "uq_events_v3_entity_block" in str(exc.value)
    finally:
        db.rollback()
        db.close()


def _constraint_exists():
    with engine.connect() as c:
        return c.execute(text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_events_v3_entity_block'")).first() is not None


def test_init_db_adds_the_constraint_to_an_existing_table_and_skips_when_forks_exist(client):
    from app.core.database import _ensure_chain_unique_constraint
    with engine.begin() as c:
        c.execute(text("ALTER TABLE events_v3 DROP CONSTRAINT IF EXISTS uq_events_v3_entity_block"))
    _ensure_chain_unique_constraint()
    assert _constraint_exists()

    # pre-existing fork: must not fail startup, must not add the constraint
    entity = eid()
    with engine.begin() as c:
        c.execute(text("ALTER TABLE events_v3 DROP CONSTRAINT uq_events_v3_entity_block"))
        for h in ("a" * 63 + "1", "a" * 63 + "2"):
            c.execute(text("INSERT INTO events_v3 (entity_id, event_type, payload, event_hash, block_index, created_at) "
                           "VALUES (:e, 'x', '{}', :h, 0, now())"), {"e": entity, "h": h})
    try:
        _ensure_chain_unique_constraint()
        assert not _constraint_exists()
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM events_v3 WHERE entity_id = :e"), {"e": entity})
        _ensure_chain_unique_constraint()
        assert _constraint_exists()
