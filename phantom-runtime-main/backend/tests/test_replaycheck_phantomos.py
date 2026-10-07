"""Run replaycheck (../../replaycheck) against the production PhantomOS reconstructor: replay must be
deterministic across processes with different hash seeds, clocks, RNG and uuid streams, and
apply_event must not mutate events."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "replaycheck"))

from replaycheck.checks import check_determinism, check_event_mutation  # noqa: E402
from replaycheck.util import load_module  # noqa: E402
from .test_replay_equivalence import SEQUENCE  # noqa: E402

ADAPTER = os.path.join(REPO, "replaycheck", "examples", "phantomos_adapter.py")
EVENTS = [{"event_type": t, "payload": p} for t, p in SEQUENCE]


def test_phantomos_reconstructor_is_deterministic_across_processes(client, monkeypatch):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.setenv("PYTHONPATH", backend)  # the replay workers import `app`
    assert check_determinism(ADAPTER, EVENTS, runs=3) == []


def test_phantomos_apply_event_does_not_mutate_events(client):
    mod = load_module(ADAPTER)
    assert check_event_mutation(mod, EVENTS) == []
