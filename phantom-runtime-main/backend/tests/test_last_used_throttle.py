"""verify_api_key writes last_used_at at most once a minute, not on every request."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, text

from app.core.database import SessionLocal, engine
from app.core.security import LAST_USED_RESOLUTION, SecurityManager, _last_used_is_stale


def _verify_counting_updates(raw_key):
    updates = []

    def before(conn, cur, st, params, ctx, many):
        if st.lstrip().upper().startswith("UPDATE API_KEYS"):
            updates.append(st)

    event.listen(engine, "before_cursor_execute", before)
    db = SessionLocal()
    try:
        assert SecurityManager.verify_api_key(db, raw_key) is not None
    finally:
        db.close()
        event.remove(engine, "before_cursor_execute", before)
    return len(updates)


def test_last_used_is_written_once_then_throttled(client, admin_key):
    assert _verify_counting_updates(admin_key) == 1      # never used: written
    assert _verify_counting_updates(admin_key) == 0      # used a moment ago: not rewritten
    assert _verify_counting_updates(admin_key) == 0

    h = SecurityManager.hash_key(admin_key)
    old = datetime.now(timezone.utc) - LAST_USED_RESOLUTION - timedelta(seconds=5)
    with engine.begin() as conn:
        conn.execute(text("UPDATE api_keys SET last_used_at = :t WHERE key_hash = :h"),
                     {"t": old.replace(tzinfo=None), "h": h})
    assert _verify_counting_updates(admin_key) == 1      # older than the resolution: written again


def test_stale_rule():
    now = datetime.now(timezone.utc)
    assert _last_used_is_stale(None)
    assert not _last_used_is_stale(now - timedelta(seconds=5))
    assert _last_used_is_stale(now - LAST_USED_RESOLUTION - timedelta(seconds=1))
    assert _last_used_is_stale(now + timedelta(hours=2))  # skewed into the future: self-heals
    assert not _last_used_is_stale((now - timedelta(seconds=5)).replace(tzinfo=None))  # naive column value is UTC
