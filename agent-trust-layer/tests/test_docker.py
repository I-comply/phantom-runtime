import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.executor import DockerExecutor, ExecutorConfigError, make_executor, DEFAULT_IMAGE
from atl.gateway import Core
from atl.client import sign_request

ROOT = Path(__file__).resolve().parent.parent


def docker_ready():
    try:
        if subprocess.run(["docker", "image", "inspect", DEFAULT_IMAGE], capture_output=True, timeout=15).returncode:
            return False
        return True
    except Exception:
        return False


def atl_containers():
    r = subprocess.run(["docker", "ps", "-aq", "--filter", "name=atl-"], capture_output=True, text=True)
    return r.stdout.split()


class TestDockerConfig(unittest.TestCase):
    def test_unpinned_image_refused(self):
        with self.assertRaises(ExecutorConfigError):
            DockerExecutor(tempfile.mkdtemp(), image="python:3.12-slim")

    def test_fail_closed_without_docker(self):
        with self.assertRaises(ExecutorConfigError):
            DockerExecutor(tempfile.mkdtemp(), docker_bin="/nonexistent/docker")
        os.environ["ATL_EXECUTOR"] = "docker"
        os.environ["PATH"], old = "/nonexistent", os.environ["PATH"]
        try:
            d = Path(tempfile.mkdtemp())
            shutil.copy(ROOT / "capabilities.json", d / "capabilities.json")
            with self.assertRaises(ExecutorConfigError):
                Core(d)  # refuses to start; never degrades to subprocess
        finally:
            os.environ["PATH"] = old
            del os.environ["ATL_EXECUTOR"]

    def test_unknown_driver(self):
        os.environ["ATL_EXECUTOR"] = "bogus"
        try:
            with self.assertRaises(ExecutorConfigError):
                make_executor(tempfile.mkdtemp())
        finally:
            del os.environ["ATL_EXECUTOR"]


@unittest.skipUnless(docker_ready(), "docker daemon/pinned image not available")
class TestDocker(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.ex = DockerExecutor(self.d / "sandbox")

    def tearDown(self):
        subprocess.run(["docker", "run", "--rm", "-v", f"{self.d}:/x", DEFAULT_IMAGE, "sh", "-c", "rm -rf /x/*"],
                       capture_output=True)
        shutil.rmtree(self.d, ignore_errors=True)

    def sh(self, code):
        p = subprocess.run(self.ex.argv("atl-test-" + os.urandom(4).hex(), ("python", "-c", code)),
                           capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout + p.stderr

    def test_roundtrip(self):
        r = self.ex.run("fs_write", {"path": "a/b.txt", "content": "hi"}, 30)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.ex.run("fs_read", {"path": "a/b.txt"}, 30)["output"]["content"], "hi")
        self.assertTrue((self.d / "sandbox/a/b.txt").exists())
        self.assertTrue(self.ex.run("fs_write", {"path": "t.txt", "content": "1"}, 30, "ten")["ok"])
        self.assertTrue((self.d / "sandbox/ten/t.txt").exists())

    def test_network_blocked(self):
        rc, out = self.sh("import socket;socket.create_connection(('1.1.1.1',53),timeout=3)")
        self.assertNotEqual(rc, 0)
        rc, out = self.sh("import os;print(sorted(os.listdir('/sys/class/net')))")
        self.assertEqual(out.strip(), "['lo']")

    def test_rootfs_read_only_and_tmp_noexec(self):
        rc, out = self.sh("open('/etc/x','w')")
        self.assertIn("Read-only file system", out)
        rc, out = self.sh("open('/usr/x','w')")
        self.assertIn("Read-only file system", out)
        rc, out = self.sh("import os,stat;p='/tmp/t';open(p,'w').write('#!/bin/sh\\necho hi');os.chmod(p,0o755);os.execv(p,[p])")
        self.assertNotEqual(rc, 0)
        rc, out = self.sh("open('/atl/worker.py','a')")
        self.assertNotEqual(rc, 0)

    def test_unprivileged(self):
        rc, out = self.sh("import os;print(os.getuid(),os.getgid());print(open('/proc/self/status').read())")
        self.assertTrue(out.startswith("65534 65534"))
        self.assertIn("CapEff:\t0000000000000000", out)
        self.assertIn("NoNewPrivs:\t1", out)

    def test_no_docker_socket(self):
        rc, out = self.sh("import os;print(os.path.exists('/var/run/docker.sock'))")
        self.assertEqual(out.strip(), "False")

    def test_path_and_symlink_escape(self):
        for pth in ("../x", "/etc/passwd", "a/../../x"):
            r = self.ex.run("fs_write", {"path": pth, "content": "x"}, 30)
            self.assertFalse(r["ok"]); self.assertIn("path_escape", r["error"])
        os.symlink("/etc", self.ex.box("t1") / "link")
        r = self.ex.run("fs_read", {"path": "link/passwd"}, 30, "t1")
        self.assertFalse(r["ok"]); self.assertIn("path_escape", r["error"])

    def test_timeout_kills_container(self):
        before = set(atl_containers())
        slow = self.ex.argv
        self.ex.argv = lambda name, cmd=None, box=None: slow(name, ("python", "-c", "import time;time.sleep(60)"), box=box)
        r = self.ex.run("echo", {"text": "x"}, 3)
        self.ex.argv = slow
        self.assertEqual(r["error"], "timeout")
        self.assertEqual(set(atl_containers()) - before, set())

    def test_failure_leaves_no_container(self):
        before = set(atl_containers())
        r = self.ex.run("nope", {}, 30)
        self.assertFalse(r["ok"])
        self.assertEqual(set(atl_containers()) - before, set())

    def test_executor_error_fails_closed(self):
        self.ex.image = "python@sha256:" + "0" * 64
        r = self.ex.run("echo", {"text": "x"}, 30)
        self.assertFalse(r["ok"])
        self.assertTrue(r["error"].startswith("executor:") or r["error"] == "bad_worker_output")

    def test_gateway_end_to_end(self):
        os.environ["ATL_EXECUTOR"] = "docker"
        try:
            shutil.copy(ROOT / "capabilities.json", self.d / "capabilities.json")
            c = Core(self.d)
            self.assertEqual(c.executor.name, "docker")
            w = c.admin_principal("issue", "acme", "writer")
            r = c.invoke(sign_request(w["secret"], "acme", "writer", 1, "fs_write", {"path": "z.txt", "content": "q"}))
            self.assertEqual(r["status"], 200, r)
            self.assertTrue(c.verify_all("acme")["ok"])
        finally:
            del os.environ["ATL_EXECUTOR"]


if __name__ == "__main__":
    unittest.main()
