"""Runs plugin/strategy code in an isolated subprocess (sandbox_worker.py) instead
of in-process exec(). See sandbox_worker.py's docstring for what this does and
does not guarantee.

IMPORTANT: dropping to an unprivileged user (SANDBOX_UID/GID, default 65534
"nobody") is not optional. Tested in this codebase: a textbook restricted-exec()
escape (walking ().__class__.__bases__[0].__subclasses__() to reach the `os`
module through bare `except:`, which needs no blocked builtin name) reaches
os.popen() and runs arbitrary shell commands. As root, that escape ran commands
as uid 0 and RLIMIT_NPROC was silently not enforced (Linux does not apply
RLIMIT_NPROC to root). Dropping to uid/gid 65534 makes the same escape land as
an unprivileged user with no write access outside its own rlimits, and makes
RLIMIT_NPROC actually bind (fork/popen then fails). This does not make exec()
safe — it bounds how much damage a successful escape can do. Prefer the Docker
executor (ATL_EXECUTOR-style, network-isolated, read-only rootfs) over this
plain-subprocess fallback wherever Docker is available; see
agent-trust-layer/atl/executor.py in this repo for that reference implementation."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

WORKER = Path(__file__).with_name("sandbox_worker.py")
DEFAULT_TIMEOUT_S = 5
# 65534 is the conventional "nobody" uid/gid on Linux containers; overridable
# for environments where nobody is mapped differently.
SANDBOX_UID = int(os.environ.get("SANDBOX_UID", "65534"))
SANDBOX_GID = int(os.environ.get("SANDBOX_GID", "65534"))
# python:3.12-slim, pinned by digest — same base image agent-trust-layer/atl/executor.py
# uses, for the same reason (never pull a mutable tag for a sandbox image).
DEFAULT_IMAGE = "python@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d"


def _parse_worker_output(stdout: bytes, stderr: bytes) -> dict:
    try:
        out = json.loads(stdout.decode() or "{}")
    except ValueError:
        out = {"ok": False, "error": f"bad_worker_output: {stderr.decode()[:300]}"}
    if not isinstance(out, dict) or "ok" not in out:
        out = {"ok": False, "error": "bad_worker_output"}
    return out


def _run_subprocess(payload: bytes, timeout: float) -> dict:
    """Plain-subprocess driver: separate process, unprivileged user, rlimits.
    Blocks fork/exec (RLIMIT_NPROC=0 as a non-root user) and reads of anything
    the sandbox uid can't read. Does NOT block outbound network from the
    sandboxed code — prefer SANDBOX_EXECUTOR=docker when that matters."""
    run_kwargs = dict(
        input=payload,
        capture_output=True,
        timeout=timeout,
        env={"PATH": "/usr/bin:/bin"},  # no DATABASE_URL, no secrets, nothing from the app's env
    )
    if hasattr(os, "getuid"):
        run_kwargs["user"] = SANDBOX_UID
        run_kwargs["group"] = SANDBOX_GID
    try:
        proc = subprocess.run([sys.executable, "-I", str(WORKER)], **run_kwargs)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"sandbox unavailable: {e}"}
    except PermissionError as e:
        # Can't drop privilege to SANDBOX_UID/GID (not running as root / missing
        # CAP_SETUID). Fail closed rather than silently run as the app's own user.
        return {"ok": False, "error": f"sandbox cannot drop privileges: {e}"}
    return _parse_worker_output(proc.stdout, proc.stderr)


def _run_docker(payload: bytes, timeout: float) -> dict:
    """Docker driver: one throwaway container per call, --network none,
    read-only rootfs, all caps dropped, unprivileged user — the same pattern as
    agent-trust-layer/atl/executor.py's DockerExecutor in this repo. Fails
    closed: any Docker error is a sandbox failure, never a silent fallback to
    the plain-subprocess driver."""
    image = os.environ.get("SANDBOX_DOCKER_IMAGE", DEFAULT_IMAGE)
    name = f"phantom-sandbox-{uuid.uuid4().hex[:16]}"
    argv = [
        "docker", "run", "--rm", "-i", "--name", name,
        "--pull", "never", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "32",
        "--memory", "128m", "--memory-swap", "128m", "--cpus", "1",
        "--user", f"{SANDBOX_UID}:{SANDBOX_GID}",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=8m",
        "-v", f"{WORKER}:/sandbox/sandbox_worker.py:ro",
        "-w", "/sandbox", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
        image, "python", "-I", "sandbox_worker.py",
    ]
    try:
        proc = subprocess.run(argv, input=payload, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
        return {"ok": False, "error": "timeout"}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"docker unavailable: {e}"}
    return _parse_worker_output(proc.stdout, proc.stderr)


def run_sandboxed(code: str, local_vars: dict, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """Returns {"ok": bool, "result"|"error": ..., "duration_ms": int}.
    Never raises for a sandboxed failure (bad code, timeout, resource limit,
    escaped-but-contained code) — only for something wrong with the sandbox
    mechanism itself. Driver selected by SANDBOX_EXECUTOR (default: subprocess;
    "docker" for the stronger, network-isolated option)."""
    t0 = time.time()
    try:
        payload = json.dumps({"code": code, "locals": local_vars}).encode()
    except TypeError as e:
        return {"ok": False, "error": f"locals not JSON-serializable: {e}", "duration_ms": 0}

    driver = os.environ.get("SANDBOX_EXECUTOR", "subprocess")
    if driver == "docker":
        out = _run_docker(payload, timeout)
    elif driver == "subprocess":
        out = _run_subprocess(payload, timeout)
    else:
        out = {"ok": False, "error": f"unknown SANDBOX_EXECUTOR {driver!r}"}
    out["duration_ms"] = int((time.time() - t0) * 1000)
    return out
