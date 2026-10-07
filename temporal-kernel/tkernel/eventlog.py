import json, sqlite3, threading, uuid
from .util import canon, sha256, mac, now_ms

GENESIS = "0" * 64


class Conflict(Exception):
    """expected_seq did not match the stream head (another node appended first)."""


class IntegrityError(Exception):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  wf_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL, ts INTEGER NOT NULL,
  type TEXT NOT NULL, payload TEXT NOT NULL, idem TEXT, prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL, mac TEXT,
  PRIMARY KEY(wf_id, seq));
CREATE UNIQUE INDEX IF NOT EXISTS events_idem ON events(wf_id, idem) WHERE idem IS NOT NULL;
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
"""


class EventLog:
    """Per-workflow append-only, hash-chained event streams on SQLite (WAL). Several Node objects or
    processes may share one file; appends are serialised by BEGIN IMMEDIATE and guarded by
    expected_seq (optimistic concurrency). With `key`, each event also carries an HMAC so that an
    attacker without the key cannot recompute the chain; without it the chain detects corruption only."""

    def __init__(self, path, key=None):
        self.path, self.key = str(path), key
        self._tl = threading.local()
        c = self._conn()
        c.executescript(SCHEMA)

    def _conn(self):
        c = getattr(self._tl, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=FULL")
            self._tl.c = c
        return c

    @staticmethod
    def _body(wf, seq, event_id, ts, type, payload, idem, prev):
        return {"wf_id": wf, "seq": seq, "event_id": event_id, "ts": ts, "type": type,
                "payload": payload, "idem": idem, "prev_hash": prev}

    @staticmethod
    def _row(r):
        return {"wf_id": r["wf_id"], "seq": r["seq"], "event_id": r["event_id"], "ts": r["ts"],
                "type": r["type"], "payload": json.loads(r["payload"]), "idem": r["idem"],
                "prev_hash": r["prev_hash"], "hash": r["hash"], "mac": r["mac"]}

    def head(self, wf):
        r = self._conn().execute("SELECT seq,hash FROM events WHERE wf_id=? ORDER BY seq DESC LIMIT 1",
                                 (wf,)).fetchone()
        return (r["seq"], r["hash"]) if r else (0, GENESIS)

    def read(self, wf, after=0):
        rs = self._conn().execute("SELECT * FROM events WHERE wf_id=? AND seq>? ORDER BY seq", (wf, after))
        return [self._row(r) for r in rs]

    def workflows(self):
        return [r[0] for r in self._conn().execute("SELECT DISTINCT wf_id FROM events ORDER BY wf_id")]

    def append(self, wf, expected_seq, type, payload, idem=None, ts=None):
        """Append one event at seq expected_seq+1. A repeated idem returns the original event."""
        c = self._conn()
        pl = canon(payload)
        c.execute("BEGIN IMMEDIATE")
        try:
            if idem is not None:
                r = c.execute("SELECT * FROM events WHERE wf_id=? AND idem=?", (wf, idem)).fetchone()
                if r:
                    c.execute("COMMIT")
                    e = self._row(r)
                    e["duplicate"] = True
                    return e
            last = c.execute("SELECT seq,hash FROM events WHERE wf_id=? ORDER BY seq DESC LIMIT 1",
                             (wf,)).fetchone()
            seq, prev = (last["seq"], last["hash"]) if last else (0, GENESIS)
            if seq != expected_seq:
                raise Conflict("head is %d, expected %d" % (seq, expected_seq))
            e = self._body(wf, seq + 1, str(uuid.uuid4()), ts if ts is not None else now_ms(),
                           type, json.loads(pl), idem, prev)
            e["hash"] = sha256(canon(e))
            e["mac"] = mac(self.key, e["hash"]) if self.key else None
            c.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (wf, e["seq"], e["event_id"], e["ts"], type, pl, idem, prev, e["hash"], e["mac"]))
            c.execute("COMMIT")
            return e
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise

    def verify(self, wf):
        """Recompute the whole chain. Raises IntegrityError at the first bad event; returns head seq."""
        prev, n = GENESIS, 0
        for e in self.read(wf):
            n += 1
            if e["seq"] != n:
                raise IntegrityError("%s: gap before seq %d" % (wf, e["seq"]))
            if e["prev_hash"] != prev:
                raise IntegrityError("%s: broken link at seq %d" % (wf, n))
            body = self._body(wf, n, e["event_id"], e["ts"], e["type"], e["payload"], e["idem"], prev)
            if sha256(canon(body)) != e["hash"]:
                raise IntegrityError("%s: hash mismatch at seq %d" % (wf, n))
            if self.key:
                import hmac
                if e["mac"] is None or not hmac.compare_digest(mac(self.key, e["hash"]), e["mac"]):
                    raise IntegrityError("%s: bad mac at seq %d" % (wf, n))
            prev = e["hash"]
        return n
