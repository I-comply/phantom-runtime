"""Cross-process event fan-out over PostgreSQL LISTEN/NOTIFY.

Every worker LISTENs on one channel; publish_event NOTIFYs it. All delivery, including to clients on
the publishing worker, goes through the channel, so every worker sees the same events in the same order.

- publish() never blocks the caller or touches the SQLAlchemy pool: it enqueues, and one publisher
  thread (own autocommit connection) issues pg_notify.
- One listener thread (own connection) reads notifications and hands them to `deliver` on the loop.
- Both threads reconnect with backoff. Notifications sent while a listener is down are lost; clients
  recover through the normal endpoints (the stream carries summaries only).
- Non-PostgreSQL databases have no channel: the bus falls back to in-process delivery.
"""
import asyncio
import json
import logging
import queue
import select
import threading
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.engine import make_url

log = logging.getLogger(__name__)

CHANNEL = "phantom_events"
MAX_PAYLOAD_BYTES = 7500          # PostgreSQL limit is 8000
QUEUE_MAX = 10000
RECONNECT_MIN_S, RECONNECT_MAX_S = 0.5, 10.0
SUMMARY_KEYS = ("id", "entity_id", "event_type")

Deliver = Callable[[Dict[str, Any], str], Awaitable[None]]


def _dsn(database_url: str) -> Optional[str]:
    """libpq DSN for a PostgreSQL SQLAlchemy URL, else None."""
    url = make_url(database_url)
    if not url.get_backend_name().startswith("postgres"):
        return None
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def encode(message: Dict[str, Any], tenant_id: str) -> str:
    """Envelope for the channel; shrinks the event data to its ids if the payload would exceed the limit."""
    raw = json.dumps({"t": tenant_id, "m": message}, default=str)
    if len(raw.encode()) > MAX_PAYLOAD_BYTES:
        data = message.get("data") or {}
        slim = dict(message, data={k: data[k] for k in SUMMARY_KEYS if k in data})
        raw = json.dumps({"t": tenant_id, "m": slim}, default=str)
    return raw


class EventBus:
    def __init__(self, database_url: str):
        self.dsn = _dsn(database_url)
        self._deliver: Optional[Deliver] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._queue: "queue.Queue[str]" = queue.Queue(QUEUE_MAX)
        self._threads = []

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._loop

    @property
    def shared(self) -> bool:
        return self.dsn is not None

    def start(self, loop: asyncio.AbstractEventLoop, deliver: Deliver) -> None:
        if self._threads:
            return
        self._loop, self._deliver = loop, deliver
        self._stop.clear()
        if not self.shared:
            return
        for target, name in ((self._listen, "bus-listen"), (self._publish, "bus-publish")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        self._ready.wait(5.0)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=3.0)
        self._threads = []
        self._loop = self._deliver = None
        self._ready.clear()

    def publish(self, message: Dict[str, Any], tenant_id: str) -> None:
        """Fire-and-forget; never raises, never blocks."""
        loop = self._loop
        if loop is None or loop.is_closed() or self._deliver is None:
            return
        if not self.shared:
            asyncio.run_coroutine_threadsafe(self._deliver(message, tenant_id), loop)
            return
        try:
            self._queue.put_nowait(encode(message, tenant_id))
        except queue.Full:
            log.error("event bus queue full; dropping event")

    # -- threads ---------------------------------------------------------------------------------

    def _connect(self):
        import psycopg2
        conn = psycopg2.connect(self.dsn)
        conn.autocommit = True
        return conn

    def _backoff(self, delay: float) -> float:
        self._stop.wait(delay)
        return min(delay * 2, RECONNECT_MAX_S)

    def _listen(self) -> None:
        delay = RECONNECT_MIN_S
        while not self._stop.is_set():
            conn = None
            try:
                conn = self._connect()
                conn.cursor().execute(f"LISTEN {CHANNEL}")
                self._ready.set()
                delay = RECONNECT_MIN_S
                while not self._stop.is_set():
                    if not select.select([conn], [], [], 1.0)[0]:
                        continue
                    conn.poll()
                    while conn.notifies:
                        self._dispatch(conn.notifies.pop(0).payload)
            except Exception as e:
                log.error("event bus listener error: %s", e)
                delay = self._backoff(delay)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def _dispatch(self, payload: str) -> None:
        loop, deliver = self._loop, self._deliver
        if loop is None or deliver is None or loop.is_closed():
            return
        try:
            env = json.loads(payload)
            asyncio.run_coroutine_threadsafe(deliver(env["m"], env["t"]), loop)
        except Exception as e:
            log.error("bad event bus payload: %s", e)

    def _publish(self) -> None:
        delay = RECONNECT_MIN_S
        pending: Optional[str] = None
        while not self._stop.is_set():
            conn = None
            try:
                conn = self._connect()
                cur = conn.cursor()
                delay = RECONNECT_MIN_S
                while not self._stop.is_set():
                    if pending is None:
                        try:
                            pending = self._queue.get(timeout=1.0)
                        except queue.Empty:
                            continue
                    cur.execute("SELECT pg_notify(%s, %s)", (CHANNEL, pending))
                    pending = None
            except Exception as e:
                log.error("event bus publisher error: %s", e)
                delay = self._backoff(delay)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass


from app.core.config import settings  # noqa: E402

bus = EventBus(settings.DATABASE_URL)
