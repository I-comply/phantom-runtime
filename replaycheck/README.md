# replaycheck

Audits an event-sourced system against its own event store: is `state == fold(events)`, every time?
Python 3.9+, stdlib only. Status: v0.1, local only.

    ./verify.sh
    python3 -m replaycheck run --store events.jsonl --reducer my_reducer.py
    python3 -m replaycheck run --store app.db --table events --payload-col payload --order-col seq \
        --reducer my_reducer.py --snapshots snaps.db --projection proj.py --live live.json --upcast up.py

Exit code: 0 pass, 1 findings, 2 usage/error. `--format json` for machines.

## In this repo
`examples/phantomos_adapter.py` wraps PhantomOS's production reconstructor (`StateReconstructorV2`);
`phantom-runtime-main/backend/tests/test_replaycheck_phantomos.py` runs the determinism and event-mutation
checks against it in CI. Agent-Trust-Layer's ledger is a hash chain verified by `atl verify`, not an
event-sourced fold, so replaycheck does not apply to it. `temporal-kernel` is event-sourced (state is a
fold of its log) and could get an adapter the same way.

## Adapter (you write this, two functions)
```python
def initial(): return {...}              # JSON-serializable state
def apply(state, event): return {...}    # must return the new state; must not mutate event
```

## Checks
| Check | What it does | Finding points at |
|---|---|---|
| determinism | Folds in N fresh processes (default 3), each with a different `PYTHONHASHSEED`, patched `time.time/monotonic/perf_counter`, `datetime.now/utcnow`, `random` seed and `uuid.uuid4` stream. Compares a state digest after every event. | first diverging event number and field |
| event-mutation | `apply()` must not change its input event. | the event |
| state-type | State must be canonical JSON (no sets, NaN, objects). | the event |
| snapshot | Each stored snapshot (`seq` = events applied) equals replay to that point. | the snapshot's event number and field |
| projection | `rebuild(events)` from scratch equals the live projection (JSON file, or SQLite `--live-query`; optional `normalize_live`). | first differing field |
| upcast | `upcast(event)` is idempotent, passes optional `validate(event)->[errors]`; warns if it mutates its input. | the event |

## Seeded-bug test fixtures
Reducers using `time.time()`, `uuid4()`, set iteration order, float accumulation order, mutating the event, raising, returning non-JSON state; stale projection; wrong snapshot; non-idempotent upcast. Each fails with a pointer; the clean reducer passes.

## Limits
- Stores: JSONL and SQLite only. No Postgres adapter yet. No pytest plugin yet.
- Python reducers only (language-agnostic via JSON stdin/stdout adapter is not built).
- Perturbs time, RNG, uuid4 and hash seed. Does not catch `date.today()`, `os.urandom`, `secrets`, network/env/filesystem reads, or thread ordering.
- Determinism evidence is sampled (N runs), not proof. Raise `--runs` for more confidence.
- It audits a reducer you hand it. It cannot tell if the reducer matches your production code.
- No claim that nothing like it exists; searches found no close match but coverage was incomplete.
