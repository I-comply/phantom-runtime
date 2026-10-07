"""Self-healing SQLite replication over local sockets.

Single-writer (leader) topology. After every commit the leader checkpoints the
WAL into the main file, diffs per-page hashes against its manifest, and pushes
the changed pages (a delta) to peers. Every node keeps a manifest of page
hashes; a scrub compares the file against it, and damaged or missing pages are
re-fetched from any peer that holds a page with the expected hash. Fetched
pages are hash-verified before being written, and every frame is HMAC'd with a
shared secret.

Limitation: a leader crash between commit and publish leaves the manifest
behind the file; the next scrub would treat those pages as corrupt.
"""
import hashlib, hmac, json, os, socket, socketserver, sqlite3, struct, threading

MAX_JSON = 16 << 20
MAX_BLOB = 256 << 20


def page_hash(b):
    return hashlib.blake2b(b, digest_size=16).hexdigest()


def _recv(sock, n):
    buf = bytearray()
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            raise ConnectionError("closed")
        buf += c
    return bytes(buf)


def send_frame(sock, secret, meta, blob=b""):
    j = json.dumps(meta, separators=(",", ":")).encode()
    head = struct.pack(">II", len(j), len(blob))
    mac = hmac.new(secret, head + j + blob, "sha256").digest()
    sock.sendall(head + j + blob + mac)


def recv_frame(sock, secret):
    head = _recv(sock, 8)
    jl, bl = struct.unpack(">II", head)
    if jl > MAX_JSON or bl > MAX_BLOB:
        raise ValueError("frame too large")
    j, blob, mac = _recv(sock, jl), _recv(sock, bl), _recv(sock, 32)
    if not hmac.compare_digest(mac, hmac.new(secret, head + j + blob, "sha256").digest()):
        raise PermissionError("bad frame MAC")
    return json.loads(j), blob


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        node = self.server.node
        try:
            while True:
                meta, blob = recv_frame(self.request, node.secret)
                rm, rb = node._dispatch(meta, blob)
                send_frame(self.request, node.secret, rm, rb)
        except (ConnectionError, PermissionError, ValueError, OSError):
            return


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Node:
    def __init__(self, path, secret, role="follower", host="127.0.0.1", port=0,
                 peers=(), page_size=4096, timeout=5.0):
        self.path = str(path)
        self.secret = secret if isinstance(secret, bytes) else secret.encode()
        self.role = role
        self.peers = list(peers)  # [(host, port)]
        self.timeout = timeout
        self.lock = threading.RLock()
        self._conn = None
        self._mpath = self.path + ".manifest"
        self.gen, self.page_size, self.hashes = 0, page_size, []
        self.stats = {"healed": 0, "unhealable": 0, "applied": 0}
        self._load_manifest()
        self._srv = _Server((host, port), _Handler)
        self._srv.node = self
        self.addr = self._srv.server_address
        self._stop = threading.Event()
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    # ---- lifecycle -------------------------------------------------------
    def close(self):
        self._stop.set()
        self._srv.shutdown()
        self._srv.server_close()
        with self.lock:
            self._close_conn()

    def start_scrubber(self, interval=5.0):
        def run():
            while not self._stop.wait(interval):
                try:
                    self.sync_and_heal()
                except Exception:
                    pass
        threading.Thread(target=run, daemon=True).start()

    # ---- local database --------------------------------------------------
    def _db(self):
        if self._conn is None:
            c = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            if self.role == "leader":
                c.execute(f"PRAGMA page_size={self.page_size}")
            c.execute("PRAGMA journal_mode=WAL")
            self._conn = c
        return self._conn

    def _close_conn(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def execute(self, sql, params=()):
        """Run one write transaction on the leader, then replicate it."""
        if self.role != "leader":
            raise PermissionError("writes are only accepted by the leader")
        with self.lock:
            c = self._db()
            c.execute("BEGIN IMMEDIATE")
            try:
                cur = c.execute(sql, params)
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            self._publish()
            return cur.rowcount

    def query(self, sql, params=()):
        with self.lock:
            return [tuple(r) for r in self._db().execute(sql, params)]

    def integrity_ok(self):
        try:
            with self.lock:
                return self._db().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        except sqlite3.DatabaseError:
            return False

    # ---- page / manifest helpers ----------------------------------------
    def _load_manifest(self):
        try:
            with open(self._mpath) as f:
                m = json.load(f)
            self.gen, self.page_size, self.hashes = m["gen"], m["page_size"], m["pages"]
        except (OSError, ValueError, KeyError):
            pass

    def _save_manifest(self):
        tmp = self._mpath + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"gen": self.gen, "page_size": self.page_size, "pages": self.hashes}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._mpath)

    def _file_pages(self):
        try:
            with open(self.path, "rb") as f:
                data = f.read()
        except OSError:
            return []
        ps = self.page_size
        return [data[i:i + ps] for i in range(0, len(data), ps)]

    def _checkpoint(self):
        if self._conn is not None:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _publish(self):
        self._checkpoint()
        pages = self._file_pages()
        new = [page_hash(p) for p in pages]
        if self._conn is not None and not self.hashes:
            self.page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
            pages = self._file_pages()
            new = [page_hash(p) for p in pages]
        changed = [i for i, h in enumerate(new) if i >= len(self.hashes) or self.hashes[i] != h]
        if not changed and len(new) == len(self.hashes):
            return
        base = self.gen
        self.hashes, self.gen = new, self.gen + 1
        self._save_manifest()
        blob = b"".join(pages[i] for i in changed)
        meta = {"op": "delta", "base": base, "gen": self.gen, "ps": self.page_size,
                "n": len(new), "idx": changed, "h": [new[i] for i in changed]}
        for peer in self.peers:
            try:
                r, _ = self._call(peer, meta, blob)
                if not r.get("ok"):
                    self._call(peer, {"op": "pull_from", "src": list(self.addr)})
            except (OSError, ConnectionError, PermissionError, ValueError):
                pass  # peer will catch up via anti-entropy

    def _write_pages(self, n, ps, items):
        """items: {idx: bytes}. Replace pages, resize file, drop stale WAL."""
        self._close_conn()
        for suffix in ("-wal", "-shm"):
            try:
                os.remove(self.path + suffix)
            except OSError:
                pass
        mode = "r+b" if os.path.exists(self.path) else "w+b"
        with open(self.path, mode) as f:
            for i, b in items.items():
                f.seek(i * ps)
                f.write(b)
            f.truncate(n * ps)
            f.flush()
            os.fsync(f.fileno())

    # ---- network ---------------------------------------------------------
    def _call(self, peer, meta, blob=b""):
        with socket.create_connection(tuple(peer), timeout=self.timeout) as s:
            send_frame(s, self.secret, meta, blob)
            return recv_frame(s, self.secret)

    def _dispatch(self, meta, blob):
        op = meta.get("op")
        with self.lock:
            if op == "manifest":
                return {"gen": self.gen, "ps": self.page_size, "pages": self.hashes}, b""
            if op == "pages":
                ps, out, idx = self.page_size, [], []
                with open(self.path, "rb") as f:
                    for i in meta["idx"]:
                        f.seek(i * ps)
                        b = f.read(ps)
                        # only serve pages that match the manifest
                        if i < len(self.hashes) and page_hash(b) == self.hashes[i]:
                            idx.append(i)
                            out.append(b)
                return {"idx": idx}, b"".join(out)
            if op == "delta":
                return {"ok": self._apply_delta(meta, blob)}, b""
        if op == "pull_from":
            threading.Thread(target=self.catch_up, args=(tuple(meta["src"]),), daemon=True).start()
            return {"ok": True}, b""
        return {"error": "unknown op"}, b""

    def _apply_delta(self, m, blob):
        if self.role == "leader" or m["base"] != self.gen or m["ps"] != self.page_size and self.hashes:
            return False
        ps = m["ps"]
        if len(blob) != ps * len(m["idx"]):
            return False
        items = {}
        for k, i in enumerate(m["idx"]):
            b = blob[k * ps:(k + 1) * ps]
            if page_hash(b) != m["h"][k]:
                return False
            items[i] = b
        new = list(self.hashes[:m["n"]]) + [None] * max(0, m["n"] - len(self.hashes))
        for i, b in items.items():
            new[i] = m["h"][m["idx"].index(i)]
        if None in new:
            return False
        self._write_pages(m["n"], ps, items)
        self.page_size, self.hashes, self.gen = ps, new, m["gen"]
        self._save_manifest()
        self.stats["applied"] += 1
        return True

    def _fetch(self, peer, idx, expect):
        """Fetch pages from peer; return only those whose hash matches expect[i]."""
        got = {}
        for s in range(0, len(idx), 256):
            part = idx[s:s + 256]
            r, blob = self._call(peer, {"op": "pages", "idx": part})
            ps = self.page_size
            for k, i in enumerate(r["idx"]):
                b = blob[k * ps:(k + 1) * ps]
                if i in expect and page_hash(b) == expect[i]:
                    got[i] = b
        return got

    # ---- anti-entropy ----------------------------------------------------
    def catch_up(self, peer):
        """Adopt a peer's newer state by fetching only the differing pages."""
        for _ in range(3):
            r, _ = self._call(peer, {"op": "manifest"})
            with self.lock:
                if r["gen"] <= self.gen:
                    return False
                ps = r["ps"]
                files = self._file_pages() if ps == self.page_size else []
                need = {i: h for i, h in enumerate(r["pages"])
                        if i >= len(files) or page_hash(files[i]) != h}
                self.page_size = ps
                got = self._fetch(peer, sorted(need), need) if need else {}
                if len(got) != len(need):
                    continue  # peer moved on; retry with a fresh manifest
                self._write_pages(len(r["pages"]), ps, got)
                self.hashes, self.gen = r["pages"], r["gen"]
                self._save_manifest()
                self.stats["applied"] += 1
                return True
        return False

    def scrub(self):
        """Indices of pages whose on-disk bytes disagree with the manifest."""
        with self.lock:
            self._checkpoint_safe()
            files = self._file_pages()
            bad = [i for i, h in enumerate(self.hashes)
                   if i >= len(files) or page_hash(files[i]) != h]
            return bad

    def _checkpoint_safe(self):
        try:
            self._checkpoint()
        except sqlite3.DatabaseError:
            self._close_conn()

    def heal(self):
        """Repair corrupt/missing pages from peers. Returns unrepaired indices."""
        with self.lock:
            bad = self.scrub()
            if not bad:
                return []
            expect = {i: self.hashes[i] for i in bad}
            fixed = {}
            for peer in self.peers:
                want = [i for i in bad if i not in fixed]
                if not want:
                    break
                try:
                    fixed.update(self._fetch(peer, want, {i: expect[i] for i in want}))
                except (OSError, ConnectionError, PermissionError, ValueError):
                    continue
            if fixed:
                self._write_pages(len(self.hashes), self.page_size, fixed)
            left = [i for i in bad if i not in fixed]
            self.stats["healed"] += len(fixed)
            self.stats["unhealable"] = len(left)
            return left

    def sync_and_heal(self):
        for peer in self.peers:
            try:
                self.catch_up(peer)
            except (OSError, ConnectionError, PermissionError, ValueError):
                pass
        return self.heal()
