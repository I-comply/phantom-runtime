"""Request sessions are capped below the connection pool, so a burst cannot deadlock the pool.

Every request runs several steps in the thread pool (40 slots) and keeps its connection, with a
transaction open, between steps: an auth lookup, `db.refresh` after a commit, the response
serialization. Under a burst, the requests holding connections wait for a free slot while the slots are
taken by newer requests blocked waiting for a connection; each wait ends only at the 30 s pool timeout.
Observed: a 200 VU burst got 202 responses in 40 s, all timeouts, and 15 connections stayed
`idle in transaction` for 2.5 minutes after the load stopped. get_db now admits at most
MAX_CONCURRENT_SESSIONS requests, which is below the pool's capacity, so checkout never blocks.
"""
import asyncio
import threading
import time

from sqlalchemy import text

from app.core.database import MAX_CONCURRENT_SESSIONS, POOL_HEADROOM, background_session, engine, get_db


def test_request_and_background_session_caps_fit_in_the_pool():
    capacity = engine.pool.size() + engine.pool._max_overflow
    assert 0 < MAX_CONCURRENT_SESSIONS and 0 < POOL_HEADROOM
    assert MAX_CONCURRENT_SESSIONS + POOL_HEADROOM <= capacity


def test_background_sessions_are_capped_and_queue_the_rest():
    """Websocket auth/metrics sessions run in worker threads, outside get_db's cap."""
    before = engine.pool.checkedout()
    lock = threading.Lock()
    active = peak = 0

    def one():
        nonlocal active, peak
        with background_session() as db:
            db.execute(text("SELECT 1"))
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1

    threads = [threading.Thread(target=one) for _ in range(POOL_HEADROOM * 4)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert not any(t.is_alive() for t in threads)
    assert peak == POOL_HEADROOM
    assert engine.pool.checkedout() == before


def test_get_db_admits_no_more_sessions_than_the_cap_and_queues_the_rest():
    before = engine.pool.checkedout()
    peak = active = 0

    async def one():
        nonlocal peak, active
        gen = get_db()
        db = await gen.__anext__()
        db.execute(text("SELECT 1"))
        active += 1
        peak = max(peak, active, engine.pool.checkedout() - before)
        await asyncio.sleep(0.02)
        active -= 1
        await gen.aclose()

    async def run():
        await asyncio.wait_for(asyncio.gather(*[one() for _ in range(MAX_CONCURRENT_SESSIONS * 3)]), 30)

    asyncio.run(run())
    assert peak == MAX_CONCURRENT_SESSIONS
    assert engine.pool.checkedout() == before


def test_get_db_cleanup_does_not_need_a_thread_pool_slot():
    """A sync generator dependency is closed in the thread pool, so a request that has read from the
    database waits for a free slot to give its connection back. get_db must close on the event loop."""
    before = engine.pool.checkedout()

    async def run():
        gen = get_db()
        db = await gen.__anext__()
        db.execute(text("SELECT 1"))
        assert engine.pool.checkedout() == before + 1
        await gen.aclose()

    asyncio.run(run())
    assert engine.pool.checkedout() == before
