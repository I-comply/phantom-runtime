"""replaycheck adapter for PhantomOS (phantom-runtime-main/backend): the production reconstructor.

    # from the repo root:
    PYTHONPATH=phantom-runtime-main/backend python3 -m replaycheck run \
        --store events.jsonl --reducer replaycheck/examples/phantomos_adapter.py

events.jsonl: one {"event_type": ..., "payload": {...}} per line, in id order (export from the
`events` table: SELECT event_type, payload FROM events WHERE entity_id = ... ORDER BY id).
"""
from types import SimpleNamespace

from app.core.reconstructor_v2 import StateReconstructorV2


def initial():
    return {}


def apply(state, event):
    # apply_event mutates `state` in place and never writes through into the event
    StateReconstructorV2.apply_event(state, SimpleNamespace(event_type=event["event_type"], payload=event["payload"]))
    return state
