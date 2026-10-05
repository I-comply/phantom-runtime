"""Standalone sandbox worker for plugin/strategy code. Runs as a SEPARATE OS process
(never imported into the FastAPI app), invoked as:

    python -I sandbox_worker.py

Reads one JSON object from stdin: {"code": str, "locals": {...}}. Writes one JSON
object to stdout: {"ok": bool, "result": ..., "error": "..."}.

Isolation properties, and their limits:
- Separate process: the code can't read the parent's memory, DB connection, or
  env vars (PATH is deliberately the only env var set by the caller — see sandbox.py).
- rlimits (CPU time, address space, no forking, no file writes) bound runaway
  code and block writing to disk or spawning children.
- `-I` (isolated mode) ignores PYTHONPATH/site customization.
- The restricted `__builtins__` dict is defense in depth, NOT a security boundary
  by itself — it is well known to be escapable via attribute-chain tricks (e.g.
  `().__class__.__bases__[0].__subclasses__()`) that need no blocked builtin name.
  The properties above (separate process, no network, no filesystem, no secrets
  in env) are what actually bound the damage if that escape is used.
- No network: nothing here binds a socket, but rlimits don't block outbound
  connections by themselves. For a stronger boundary, run this script inside a
  `--network none` container per call (see agent-trust-layer/atl/executor.py in
  this repo for a reference implementation of that pattern) rather than as a bare
  subprocess, same as that project's own README caveats for its own worker.
"""
import json
import os
import sys

MAX_OUTPUT = 1 << 20  # 1 MB


def apply_limits():
    try:
        import resource
        for res, val in (
            (resource.RLIMIT_CPU, 5),           # 5 CPU-seconds
            (resource.RLIMIT_AS, 256 << 20),    # 256 MB address space
            (resource.RLIMIT_FSIZE, 0),         # no file writes
            (resource.RLIMIT_NPROC, 0),         # no forking/spawning
            (resource.RLIMIT_NOFILE, 16),
        ):
            try:
                resource.setrlimit(res, (val, val))
            except (ValueError, OSError):
                pass
    except ImportError:
        pass  # non-POSIX platform: rlimits unavailable, rely on the timeout in sandbox.py


SAFE_BUILTINS = {
    'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool,
    'dict': dict, 'list': list, 'tuple': tuple, 'set': set,
    'sum': sum, 'max': max, 'min': min, 'abs': abs, 'round': round,
    'range': range, 'enumerate': enumerate, 'sorted': sorted, 'reversed': reversed,
    'zip': zip, 'map': map, 'filter': filter,
    'True': True, 'False': False, 'None': None,
}


def run(code: str, local_vars: dict) -> dict:
    # `json` is exposed as a convenience global (not via __builtins__) — this module's
    # own import, never anything the caller controls, so it's safe to hand to the code.
    safe_globals = {'__builtins__': dict(SAFE_BUILTINS), 'json': json}
    safe_locals = dict(local_vars)
    exec(code, safe_globals, safe_locals)  # noqa: S102 - isolated subprocess; see module docstring
    if 'result' not in safe_locals:
        raise ValueError("code must define a 'result' variable")
    return safe_locals['result']


def main():
    apply_limits()
    try:
        req = json.loads(sys.stdin.read())
        result = run(req["code"], req.get("locals", {}))
        json.dumps(result)  # fail fast here (inside try) if result isn't JSON-serializable
        out = {"ok": True, "result": result}
    except Exception as e:
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}
    data = json.dumps(out)
    if len(data) > MAX_OUTPUT:
        data = json.dumps({"ok": False, "error": "result_too_large"})
    sys.stdout.write(data)
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
