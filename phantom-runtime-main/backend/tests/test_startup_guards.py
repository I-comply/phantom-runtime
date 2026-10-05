"""Checks that only show up at import time (app.main raises before the app
object exists), so they run app.main fresh in a subprocess rather than relying
on whatever's already in sys.modules from the other test files."""
import os
import subprocess
import sys


def _run_import(env_overrides):
    env = dict(os.environ)
    env.update(env_overrides)
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=backend_dir, env=env, capture_output=True, text=True, timeout=30,
    )


def test_wildcard_cors_with_credentials_refuses_to_start():
    r = _run_import({"CORS_ORIGINS": "*"})
    assert r.returncode != 0
    assert "CORS_ORIGINS" in r.stderr


def test_explicit_cors_origin_starts_fine():
    r = _run_import({"CORS_ORIGINS": "http://localhost:3000"})
    assert r.returncode == 0, r.stderr
