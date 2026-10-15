"""Single-leader election across worker processes via a PostgreSQL session-level advisory lock.

The lock lives as long as the holder's connection, so a crashed or partitioned leader frees it
automatically and another worker takes over within RETRY_S. The leader verifies its connection every
HEARTBEAT_S and releases leadership (on_lose) if it is gone. Non-PostgreSQL databases have no such
lock: the process is its own leader (single-process deployments only).
"""
import logging
import threading
from typing import Callable, Optional

from sqlalchemy.engine import make_url

log = logging.getLogger("phantom.reconciler")

LOCK_KEY = 0x70686E746D5F7263   # arbitrary app-wide constant ("phntm_rc")
HEARTBEAT_S = 2.0
RETRY_S = 2.0


class LeaderElector:
    def __init__(self, database_url: str, on_acquire: Callable[[], None], on_lose: Callable[[], None],
                 retry_s: float = RETRY_S, heartbeat_s: float = HEARTBEAT_S, lock_key: int = LOCK_KEY):
        url = make_url(database_url)
        self.dsn = None if not url.get_backend_name().startswith("postgres") else \
            url.set(drivername="postgresql").render_as_string(hide_password=False)
        self.on_acquire, self.on_lose = on_acquire, on_lose
        self.retry_s, self.heartbeat_s, self.lock_key = retry_s, heartbeat_s, lock_key
        self.is_leader = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.dsn is None:
            self._become_leader()
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="leader-elector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._lose_leadership()

    def _become_leader(self) -> None:
        self.is_leader = True
        self.on_acquire()

    def _lose_leadership(self) -> None:
        if self.is_leader:
            self.is_leader = False
            self.on_lose()

    def _run(self) -> None:
        import psycopg2
        while not self._stop.is_set():
            conn = None
            try:
                conn = psycopg2.connect(self.dsn)
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute("SELECT pg_try_advisory_lock(%s)", (self.lock_key,))
                if cur.fetchone()[0]:
                    self._become_leader()
                    while not self._stop.wait(self.heartbeat_s):
                        cur.execute("SELECT 1")   # raises once the connection (and so the lock) is gone
            except Exception as e:
                log.error("leader election error: %s", e)
            finally:
                self._lose_leadership()
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            self._stop.wait(self.retry_s)
