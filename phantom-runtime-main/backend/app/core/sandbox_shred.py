"""In-container entrypoint for the RAM-disk overlay (see ramdisk_overlay.py).

    python -I sandbox_shred.py

Runs sandbox_worker.py (same directory) with stdin/stdout passed through, then
overwrites and unlinks every file on the RAM-backed mounts named in
SANDBOX_SHRED_DIRS (os.pathsep-separated) before exiting — on normal exit,
exception, SIGTERM and SIGINT. SIGKILL / power loss cannot be trapped; there the
guarantee is that the mounts are tmpfs, so nothing was ever on physical media
and the kernel frees the pages with the container."""
import os
import signal
import subprocess
import sys

_CHUNK = 1 << 16


def shred_tree(root: str) -> int:
    """Overwrite (zeros, then ones) and unlink every regular file under root,
    then remove empty directories. Best-effort: never raises. Returns files shredded."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                if os.path.islink(path):
                    os.unlink(path)
                    continue
                size = os.path.getsize(path)
                with open(path, "r+b", buffering=0) as f:
                    for fill in (b"\x00", b"\xff"):
                        f.seek(0)
                        left = size
                        while left > 0:
                            k = min(left, _CHUNK)
                            f.write(fill * k)
                            left -= k
                        os.fsync(f.fileno())
                os.unlink(path)
                n += 1
            except OSError:
                pass
        for name in dirnames:
            try:
                os.rmdir(os.path.join(dirpath, name))
            except OSError:
                pass
    return n


def shred_all() -> None:
    for d in filter(None, os.environ.get("SANDBOX_SHRED_DIRS", "").split(os.pathsep)):
        shred_tree(d)


_child = None


def _on_signal(signum, _frame):
    if _child is not None:
        _child.kill()
        _child.wait()
    shred_all()
    os._exit(128 + signum)


def main() -> None:
    """The worker runs as a child: it sets RLIMIT_FSIZE=0 on itself, which would
    also stop this process from overwriting files if it ran in-process."""
    global _child
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _on_signal)
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_worker.py")
    rc = 1
    try:
        _child = subprocess.Popen([sys.executable, "-I", worker])  # nosec B603
        rc = _child.wait()
    finally:
        shred_all()
    sys.exit(rc)


if __name__ == "__main__":
    main()
