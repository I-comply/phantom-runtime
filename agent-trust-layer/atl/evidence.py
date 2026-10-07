import os, tempfile
from pathlib import Path
from .util import sha256, valid_id


class Evidence:
    def __init__(self, root):
        self.root = Path(root)

    def _p(self, tenant, h):
        if not valid_id(tenant) or len(h) != 64 or any(ch not in "0123456789abcdef" for ch in h):
            raise ValueError("bad_ref")
        return self.root / tenant / h[:2] / h

    def put(self, tenant, data):
        if isinstance(data, str):
            data = data.encode()
        h = sha256(data)
        p = self._p(tenant, h)
        if not p.exists() or sha256(p.read_bytes()) != h:  # rewrite missing or corrupt blob
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        return h

    def get(self, tenant, h):
        return self._p(tenant, h).read_bytes()

    def check(self, tenant, h):
        try:
            return sha256(self.get(tenant, h)) == h
        except (OSError, ValueError):
            return False

    def erase(self, tenant, h):
        """Delete a blob. Callers must record an evidence.erased tombstone in the ledger first."""
        try:
            self._p(tenant, h).unlink()
            return True
        except FileNotFoundError:
            return False
