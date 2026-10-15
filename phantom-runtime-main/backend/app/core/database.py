import asyncio
import threading
import weakref
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# A request session holds at most one pooled connection at a time. Capping concurrent request sessions
# below the pool's capacity means a request can always get a connection, so a worker thread never blocks
# waiting for one while the requests holding connections wait for a thread (see get_db). The headroom is
# for sessions opened outside requests (background_session).
POOL_SIZE = 5
MAX_OVERFLOW = 10
POOL_HEADROOM = 3
MAX_CONCURRENT_SESSIONS = POOL_SIZE + MAX_OVERFLOW - POOL_HEADROOM

engine = create_engine(settings.DATABASE_URL, pool_size=POOL_SIZE, max_overflow=MAX_OVERFLOW)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

_session_slots: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _session_slots.get(loop)
    if sem is None:
        sem = _session_slots[loop] = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)
    return sem


_background_slots = threading.BoundedSemaphore(POOL_HEADROOM)


@contextmanager
def background_session():
    """Session for code that runs outside a request (websocket auth and metrics, which run in worker
    threads), capped at POOL_HEADROOM at once. Together with the request cap this keeps the total at or
    below the pool's capacity, so checkout never blocks. Open it, use it, close it within one thread call;
    never hold it across an await."""
    with _background_slots:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()


async def get_db():
    """Request-scoped session, at most MAX_CONCURRENT_SESSIONS at once; further requests wait here, on
    the event loop, without occupying a thread.

    Without the cap, a burst deadlocks for minutes: every request runs several steps in the thread pool
    (40 slots) and keeps its connection, with a transaction open, between steps (an auth lookup, a
    refresh after commit, the response serialization). Requests holding connections wait for a free slot,
    while the slots are taken by newer requests blocked waiting for a connection, and each wait ends
    only at the 30 s pool timeout. An async generator also closes the session on the event loop rather
    than in the thread pool. Queries still run in the sync endpoint's thread."""
    async with _slots():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

def init_db():
    # Import all models to ensure they're registered with Base
    from app.core import models  # v1 models
    from app.core import models_v2  # v2 models
    from app.core import models_v3  # v3 models
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    _ensure_chain_unique_constraint()


_CHAIN_UNIQUE_SQL = """
DO $$
BEGIN
  IF to_regclass('public.events_v3') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_events_v3_entity_block') THEN
    IF EXISTS (SELECT 1 FROM public.events_v3 GROUP BY entity_id, block_index HAVING count(*) > 1) THEN
      RAISE WARNING 'events_v3 has forked chains (duplicate entity_id, block_index); '
                    'uq_events_v3_entity_block NOT added. Resolve the duplicates, then restart.';
    ELSE
      ALTER TABLE public.events_v3
        ADD CONSTRAINT uq_events_v3_entity_block UNIQUE (entity_id, block_index);
    END IF;
  END IF;
END $$;
"""


def _ensure_chain_unique_constraint():
    """create_all never alters an existing table, so databases created before the constraint
    existed get it here. Skips (with a warning) instead of failing startup if forks already exist."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_CHAIN_UNIQUE_SQL))
