"""Plugin/strategy code runs via core/sandbox.py, never in-process exec(). These
tests cover the normal path and, more importantly, replay the actual escape
payload used during the security review to prove containment holds — not just
that auth is required to reach it."""
from .conftest import eid


def test_sandbox_mechanism_directly():
    """Bypasses HTTP/DB entirely — isolates whether a failure is in the sandbox
    mechanism itself (process spawn, privilege drop, rlimits) vs. the plugin/
    strategy engine or route layer around it. Run first/standalone so a CI
    failure here, with its full error string, is the first thing visible."""
    from app.core.sandbox import run_sandboxed
    out = run_sandboxed('result = {"x": state["a"] + 1}', {"state": {"a": 5}, "config": {}})
    assert out["ok"], f"sandbox mechanism itself failed: {out}"
    assert out["result"] == {"x": 6}

ESCAPE_PAYLOAD = '''
result = {}
for cls in ().__class__.__bases__[0].__subclasses__():
    try:
        g = cls.__init__.__globals__
    except:
        continue
    if "os" in g:
        try:
            result = {"shelled_out": g["os"].popen("id").read()}
            break
        except:
            result = {"blocked": True}
if not result:
    result = {"no_class_found": True}
'''


def test_strategy_execute_requires_auth(client, admin_key):
    strat = client.post("/api/v3/strategies", json={"name": "s", "strategy_type": "custom", "code": "result={}"},
                        headers={"X-API-Key": admin_key})
    assert strat.status_code == 200
    sid = strat.json()["id"]
    assert client.post(f"/api/v3/strategies/{sid}/execute", params={"entity_id": eid()}).status_code == 401


def test_strategy_execute_sandboxed_happy_path(client, admin_key):
    entity = eid()
    client.post("/api/v3/events", json={"entity_id": entity, "event_type": "init", "payload": {}},
               headers={"X-API-Key": admin_key})
    strat = client.post("/api/v3/strategies", json={"name": "s", "strategy_type": "custom", "code": 'result={"n": len(events)}'},
                        headers={"X-API-Key": admin_key})
    sid = strat.json()["id"]
    exe = client.post(f"/api/v3/strategies/{sid}/execute", params={"entity_id": entity}, headers={"X-API-Key": admin_key})
    assert exe.status_code == 200, exe.text
    body = exe.json()
    assert body["status"] == "completed", body


def test_plugin_execute_requires_auth(client, admin_key):
    plg = client.post("/api/plugins/", json={"name": "p", "code": "result={}"}, headers={"X-API-Key": admin_key})
    assert plg.status_code == 200
    pid = plg.json()["id"]
    assert client.post(f"/api/plugins/{pid}/execute", json={"entity_id": eid()}).status_code == 401


def test_plugin_execute_sandboxed_happy_path(client, admin_key):
    entity = eid()
    plg = client.post("/api/plugins/", json={"name": "p", "code": 'result={"ok": config.get("x", 1)}'},
                      headers={"X-API-Key": admin_key})
    pid = plg.json()["id"]
    exe = client.post(f"/api/plugins/{pid}/execute", json={"entity_id": entity}, headers={"X-API-Key": admin_key})
    assert exe.status_code == 200, exe.text


def test_sandbox_escape_attempt_does_not_get_a_shell(client, admin_key):
    """The restricted-builtins exec() IS escapable (this payload proves it reaches
    os via subclass-walk + bare except). What must hold is containment: the
    isolated-subprocess sandbox (unprivileged uid, RLIMIT_NPROC=0) blocks the
    fork that os.popen() needs, so the escape never yields a shell."""
    entity = eid()
    evil = client.post("/api/plugins/", json={"name": "evil", "code": ESCAPE_PAYLOAD}, headers={"X-API-Key": admin_key})
    pid = evil.json()["id"]
    exe = client.post(f"/api/plugins/{pid}/execute", json={"entity_id": entity}, headers={"X-API-Key": admin_key})
    assert exe.status_code == 200, exe.text
    result = exe.json().get("result", {})
    assert "shelled_out" not in result, f"sandbox escape got a shell: {result}"


def test_ramdisk_overlay_args_all_writable_paths_are_tmpfs():
    from pathlib import Path
    from app.core import ramdisk_overlay as r
    flags, cmd = r.docker_args(Path("/tmp/w.py"), 65534, 65534)
    joined = " ".join(flags)
    assert "--read-only" in flags and "--log-driver" in flags and "none" in flags
    assert "--memory-swappiness" in flags
    for p in r.RAM_MOUNTS:
        assert f"{p}:rw,noexec,nosuid,nodev," in joined
    assert cmd == ["python", "-I", "sandbox_shred.py"]
    assert all(f.endswith(":ro") for f in flags if ":/sandbox/sandbox_" in f)


def test_ramdisk_overlay_disabled_falls_back(monkeypatch):
    from pathlib import Path
    from app.core import ramdisk_overlay as r
    monkeypatch.setenv("SANDBOX_RAMDISK", "0")
    _, cmd = r.docker_args(Path("/tmp/w.py"), 1, 1)
    assert cmd == ["python", "-I", "sandbox_worker.py"]


def test_ramdisk_audit_mounts():
    from app.core.ramdisk_overlay import audit_mounts
    ok = [{"Type": "tmpfs"}, {"Type": "bind", "RW": False}]
    assert audit_mounts(ok) == []
    assert len(audit_mounts(ok + [{"Type": "volume"}, {"Type": "bind", "RW": True}])) == 2


def test_shred_tree_removes_files(tmp_path):
    from app.core.sandbox_shred import shred_tree
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "a").write_bytes(b"secret" * 1000)
    (tmp_path / "b").write_bytes(b"x")
    assert shred_tree(str(tmp_path)) == 2
    assert list(tmp_path.iterdir()) == []


def test_shred_entrypoint_passes_through_worker_io(tmp_path):
    import json, os, subprocess, sys
    from app.core.sandbox import _SOURCE_WORKER
    scratch = tmp_path / "ram"; scratch.mkdir(); (scratch / "leak").write_text("s")
    shred = _SOURCE_WORKER.with_name("sandbox_shred.py")
    proc = subprocess.run([sys.executable, "-I", str(shred)],
                          input=json.dumps({"code": "result={'v': 1}", "locals": {}}).encode(),
                          capture_output=True, env={"SANDBOX_SHRED_DIRS": str(scratch)})
    assert json.loads(proc.stdout)["result"] == {"v": 1}
    assert list(scratch.iterdir()) == []
