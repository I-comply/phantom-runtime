import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "ram_engine.sh")


def test_ram_engine_script_syntax():
    res = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_ram_engine_has_cleanup_trap():
    src = open(SCRIPT).read()
    assert "trap cleanup EXIT INT TERM" in src
    assert "tmpfs" in src
