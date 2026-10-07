import contextlib, json, sqlite3


def _ro(path):
    return contextlib.closing(sqlite3.connect("file:%s?mode=ro" % path, uri=True))


def _ident(s):
    if not s.replace("_", "").isalnum():
        raise SystemExit("error: bad SQL identifier %r" % s)
    return s


def load_events(path, table="events", payload_col="payload", order_col="rowid"):
    """JSONL file (one JSON event per line) or SQLite file. SQLite: if payload_col exists, each
    row's payload is parsed as the event; otherwise the row itself (JSON-looking columns parsed)."""
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"SQLite format 3"):
        with _ro(path) as c:
            c.row_factory = sqlite3.Row
            cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % _ident(table))]
            if not cols:
                raise SystemExit("error: table %r not found in %s" % (table, path))
            rows = c.execute("SELECT * FROM %s ORDER BY %s" % (_ident(table), _ident(order_col))).fetchall()
        out = []
        for r in rows:
            if payload_col in cols:
                v = r[payload_col]
                out.append(json.loads(v) if isinstance(v, (str, bytes)) else v)
            else:
                d = {}
                for k in cols:
                    v = r[k]
                    if isinstance(v, str) and v[:1] in "{[":
                        try:
                            v = json.loads(v)
                        except ValueError:
                            pass
                    d[k] = v
                out.append(d)
        return out
    events = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError as e:
                    raise SystemExit("error: %s line %d: %s" % (path, n, e))
    return events


def load_snapshots(path, table="snapshots"):
    """[(n_events_applied, state)]. JSONL lines {"seq": n, "state": {...}} or SQLite table(seq, state)."""
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"SQLite format 3"):
        with _ro(path) as c:
            rows = c.execute("SELECT seq, state FROM %s ORDER BY seq" % _ident(table)).fetchall()
        return [(int(s), json.loads(st) if isinstance(st, (str, bytes)) else st) for s, st in rows]
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                out.append((int(d["seq"]), d["state"]))
    return out


def load_live(path, query=None):
    if query:
        with _ro(path) as c:
            return [list(r) for r in c.execute(query).fetchall()]
    with open(path, encoding="utf-8") as f:
        return json.load(f)
