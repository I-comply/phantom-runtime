"""Synthetic demo: rebuild state from an event log with PhantomOS's production reconstructor."""
import json, sys
from types import SimpleNamespace
from app.core.reconstructor_v2 import StateReconstructorV2

events = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
state = {}
for i, e in enumerate(events, 1):
    StateReconstructorV2.apply_event(state, SimpleNamespace(event_type=e["event_type"], payload=e["payload"]))
    print(f"event {i}: {e['event_type']:<9} -> state {json.dumps(state, sort_keys=True)}")
