"""Rebuild stored snapshots from the event log with the current (single) reconstructor.

    python -m app.scripts.rebuild_snapshots [entity_id]

Run once after deploying the reconstructor unification: snapshots created by the old v1
reconstructor can differ from a full replay. Idempotent.
"""
import sys

from app.core.database import SessionLocal
from app.core.snapshot_manager import SnapshotManager


def main(argv):
    db = SessionLocal()
    try:
        changed = SnapshotManager.rebuild_snapshots(db, entity_id=argv[1] if len(argv) > 1 else None)
        print("snapshots rebuilt: %d" % changed)
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv)
