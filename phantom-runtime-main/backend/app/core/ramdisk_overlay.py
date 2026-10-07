"""Ephemeral RAM-disk overlay for the Docker sandbox driver.

Every writable path the container has is a size-capped tmpfs; the rootfs is
read-only; swap is disabled; no volume, bind mount (other than the read-only
worker scripts) or log file can land on physical storage. Result: nothing the
sandboxed code writes ever touches disk, so there is nothing to recover after
the process ends or power is lost.

Shredding triggers (see sandbox_shred.py): normal exit, exception, SIGTERM,
SIGINT, SIGHUP inside the container; `docker rm -f -v` from the host on
timeout. SIGKILL/power loss rely on tmpfs volatility.

Honest limits: tmpfs pages are zeroed by the kernel on free only if the host
sets init_on_free=1 (otherwise they may linger in RAM until reused); the host's
own swap, hibernation image or crash dump can still capture container memory —
this overlay controls the container's side only. Verify the host with
`swapon --show` and keep encrypted/no swap."""
import os
import shutil
import tempfile
from pathlib import Path

_SRC_SHRED = Path(__file__).with_name("sandbox_shred.py")
_SRC_WORKER = Path(__file__).with_name("sandbox_worker.py")

# In-container paths that are writable, all RAM-backed.
RAM_MOUNTS = ("/tmp", "/var/tmp", "/run", "/sandbox/work")


def enabled() -> bool:
    return os.environ.get("SANDBOX_RAMDISK", "1") != "0"


def _size_mb() -> int:
    try:
        return max(1, int(os.environ.get("SANDBOX_RAMDISK_MB", "8")))
    except ValueError:
        return 8


def _world_readable_copy(src: Path) -> Path:
    dst = Path(tempfile.gettempdir()) / f"phantom_{src.stem}_{src.stat().st_mtime_ns}.py"
    if not dst.exists():
        shutil.copy2(src, dst)
    os.chmod(dst, 0o644)
    return dst


def docker_args(worker: Path, uid: int, gid: int) -> tuple:
    """Returns (flags, command). flags go between `docker run` and the image;
    command follows the image. When disabled, falls back to the plain layout
    (single /tmp tmpfs, worker run directly)."""
    size = _size_mb()
    flags = [
        "--read-only", "--memory-swap", "128m", "--memory-swappiness", "0",
        "--log-driver", "none",  # json-file logs would persist stdout/stderr on disk
    ]
    if not enabled():
        flags += ["--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=8m"]  # nosec B108
        flags += ["-v", f"{worker}:/sandbox/sandbox_worker.py:ro"]
        return flags, ["python", "-I", "sandbox_worker.py"]
    for path in RAM_MOUNTS:
        flags += ["--tmpfs", f"{path}:rw,noexec,nosuid,nodev,size={size}m,mode=1777"]  # nosec B108
    shred = _world_readable_copy(_SRC_SHRED)
    flags += [
        "-v", f"{worker}:/sandbox/sandbox_worker.py:ro",
        "-v", f"{shred}:/sandbox/sandbox_shred.py:ro",
        "-e", f"SANDBOX_SHRED_DIRS={os.pathsep.join(RAM_MOUNTS)}",
    ]
    return flags, ["python", "-I", "sandbox_shred.py"]


def host_cleanup_args(name: str) -> list:
    """Host-side forced teardown: -v also drops any anonymous volume."""
    return ["docker", "rm", "-f", "-v", name]


def audit_mounts(inspect_mounts: list) -> list:
    """Given `docker inspect` .Mounts, return violations: any volume, or any
    bind mount that is writable. Empty list == nothing can persist to disk."""
    bad = []
    for m in inspect_mounts or []:
        if m.get("Type") == "tmpfs":
            continue
        if m.get("Type") == "bind" and m.get("RW") is False:
            continue
        bad.append(m)
    return bad
