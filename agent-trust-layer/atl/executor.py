import json, os, re, subprocess, sys, time, uuid
from pathlib import Path

WORKER = Path(__file__).with_name("worker.py")
# python:3.12-slim, pinned by digest. Override with ATL_DOCKER_IMAGE (must also be digest-pinned).
DEFAULT_IMAGE = "python@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d"
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
MAX_OUT = 1 << 21
TMPFS = "/tmp:rw,noexec,nosuid,nodev,size=16m"  # nosec B108


class ExecutorConfigError(Exception):
    pass


def _parse(stdout):
    out = json.loads(stdout[:MAX_OUT].decode() or "{}")
    if not isinstance(out, dict) or "ok" not in out:
        return {"ok": False, "error": "bad_worker_output"}
    return out


class SubprocessExecutor:
    name = "subprocess"

    def __init__(self, sandbox):
        self.sandbox = Path(sandbox)
        self.sandbox.mkdir(parents=True, exist_ok=True)

    def box(self, tenant):
        """Per-tenant sandbox directory (tenants never share a filesystem view)."""
        if tenant is None:
            return self.sandbox
        b = self.sandbox / tenant
        b.mkdir(parents=True, exist_ok=True)
        return b

    def _run(self, tool, params, timeout, tenant=None):
        p = subprocess.run([sys.executable, "-I", str(WORKER)],
                           input=json.dumps({"tool": tool, "params": params}).encode(),
                           capture_output=True, cwd=str(self.box(tenant)), timeout=timeout,
                           env={"PATH": "/usr/bin:/bin"})
        return _parse(p.stdout)

    def run(self, tool, params, timeout, tenant=None):
        t0 = time.time()
        try:
            out = self._run(tool, params, timeout, tenant)
        except subprocess.TimeoutExpired:
            out = {"ok": False, "error": "timeout"}
        except Exception as e:
            out = {"ok": False, "error": f"executor:{type(e).__name__}"}
        out["duration_ms"] = int((time.time() - t0) * 1000)
        return out


Executor = SubprocessExecutor


class DockerExecutor(SubprocessExecutor):
    """One throwaway container per call. Fails closed: no fallback to the subprocess driver."""
    name = "docker"

    def __init__(self, sandbox, image=None, docker_bin="docker"):
        super().__init__(sandbox)
        self.sandbox = self.sandbox.resolve()
        self.image = image or os.environ.get("ATL_DOCKER_IMAGE") or DEFAULT_IMAGE
        if not IMAGE_RE.match(self.image):
            raise ExecutorConfigError("docker image must be pinned by sha256 digest")
        self.docker = docker_bin
        self._own(self.sandbox)
        try:
            r = subprocess.run([docker_bin, "version", "--format", "{{.Server.Version}}"],
                               capture_output=True, timeout=15)
        except Exception as e:
            raise ExecutorConfigError(f"docker unavailable: {type(e).__name__}")
        if r.returncode != 0:
            raise ExecutorConfigError("docker daemon unavailable")

    @staticmethod
    def _own(path):
        """Container runs as 65534 and the sandbox is its only writable path. Prefer chown + 0700; an
        unprivileged host cannot chown, so fall back to a sticky world-writable dir (documented)."""
        try:
            os.chown(path, 65534, 65534)
            os.chmod(path, 0o700)
        except PermissionError:
            os.chmod(path, 0o1777)  # nosec B103

    def box(self, tenant):
        b = super().box(tenant)
        self._own(b)
        return b

    def argv(self, name, cmd=("python", "-I", "/atl/worker.py"), box=None):
        return [self.docker, "run", "--rm", "-i", "--name", name,
                "--pull", "never", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "64",
                "--memory", "256m", "--memory-swap", "256m", "--cpus", "1", "--user", "65534:65534",
                "--tmpfs", TMPFS,
                "-v", f"{box or self.sandbox}:/sandbox:rw",
                "-v", f"{WORKER}:/atl/worker.py:ro",
                "-w", "/sandbox", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
                self.image, *cmd]

    def _cleanup(self, name):
        subprocess.run([self.docker, "rm", "-f", name], capture_output=True, timeout=30)

    def _run(self, tool, params, timeout, tenant=None):
        name = f"atl-{uuid.uuid4().hex[:16]}"
        try:
            p = subprocess.run(self.argv(name, box=self.box(tenant)), input=json.dumps({"tool": tool, "params": params}).encode(),
                               capture_output=True, timeout=timeout)
        except BaseException:
            try:
                self._cleanup(name)  # hard kill + remove; also covers client-side timeout
            except Exception as e:
                sys.stderr.write(f"atl: container cleanup failed for {name}: {type(e).__name__}\n")
            raise
        if p.returncode not in (0, 1) and not p.stdout:
            raise RuntimeError("docker_run_failed")
        return _parse(p.stdout)


def make_executor(sandbox):
    kind = os.environ.get("ATL_EXECUTOR", "subprocess")
    if kind == "subprocess":
        return SubprocessExecutor(sandbox)
    if kind == "docker":
        return DockerExecutor(sandbox)
    raise ExecutorConfigError(f"unknown ATL_EXECUTOR {kind!r}")
