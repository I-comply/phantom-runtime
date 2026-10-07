from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.models import Event
from app.core.models_v2 import EntityWorkspace
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# The v1 Event table (above) predates multi-tenancy and has no tenant/workspace
# column of its own — adding one would need a migration + backfill. Instead,
# tenant scoping for v1 events reuses the EntityWorkspace mapping table (already
# in models_v2.py, already used by /api/workspaces/me/entities) as the source of
# truth for "which workspace does this entity_id belong to". append_event links
# an entity to its creator's workspace the first time it's written; every read
# below filters through that same link when a workspace_id is given.

class EntityOwnedElsewhere(Exception):
    """The entity already belongs to a different workspace."""


class EventStore:
    @staticmethod
    def lock_entity(db: Session, entity_id: str) -> None:
        """Serialize writers and snapshot creation for one entity until the transaction ends.

        Event ids come from a sequence and are assigned before commit, so two writers can commit
        out of id order. A snapshot cut in between would record last_event_id = N while an
        uncommitted event with id < N lands afterwards, and the incremental `id > last_event_id`
        replay would skip it forever. Holding this lock from before the insert until commit makes
        the entity's events commit in id order, and lets create_snapshot see a consistent head."""
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": "events:" + entity_id})

    @staticmethod
    def claim_entity(db: Session, entity_id: str, workspace_id: Optional[str]) -> None:
        """Link entity_id to workspace_id if it isn't linked to ANY workspace yet
        (idempotent, first-writer-wins — a tenant can never silently re-home
        another tenant's already-linked entity). No-op if workspace_id is None.
        Does not commit; caller's transaction covers it."""
        if workspace_id is None:
            return
        existing_link = db.query(EntityWorkspace).filter(
            EntityWorkspace.entity_id == entity_id
        ).first()
        if existing_link is None:
            db.add(EntityWorkspace(workspace_id=workspace_id, entity_id=entity_id))
        elif str(existing_link.workspace_id) != str(workspace_id):
            raise EntityOwnedElsewhere(entity_id)

    @staticmethod
    def check_money_rules(db: Session, entity_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """Raises money.AmountError if the event is not applicable to the entity's current state. Call
        after lock_entity, so the state can't change before the event is written."""
        from app.core import money
        if event_type not in money.RULE_CHECKED:
            return
        from app.core.snapshot_manager import SnapshotManager
        money.check_applicable(event_type, payload, SnapshotManager.reconstruct_with_snapshot(db, entity_id))

    @staticmethod
    def append_event(
        db: Session,
        entity_id: str,
        event_type: str,
        payload: Dict[str, Any],
        workspace_id: Optional[str] = None,
        validate_against_state: bool = False,
    ) -> Event:
        """Append a new event to the store. See claim_entity for the workspace_id link.
        validate_against_state applies the money rules to the entity's current state under its lock."""
        EventStore.lock_entity(db, entity_id)
        EventStore.claim_entity(db, entity_id, workspace_id)  # first: a refused write adds nothing
        if validate_against_state:
            EventStore.check_money_rules(db, entity_id, event_type, payload)
        event = Event(
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(timezone.utc)
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    @staticmethod
    def entity_in_workspace(db: Session, entity_id: str, workspace_id: str) -> bool:
        return db.query(EntityWorkspace).filter(
            EntityWorkspace.entity_id == entity_id,
            EntityWorkspace.workspace_id == workspace_id,
        ).first() is not None

    @staticmethod
    def get_events(db: Session, entity_id: str) -> List[Event]:
        """Retrieve all events for an entity in id (commit) order. Caller is
        responsible for an access check (entity_in_workspace) before calling this
        for a non-admin caller — this method itself returns unfiltered history
        for the given entity_id, same as before."""
        return db.query(Event).filter(
            Event.entity_id == entity_id
        ).order_by(Event.id.asc()).all()

    @staticmethod
    def get_all_events(db: Session, limit: int = 100, workspace_id: Optional[str] = None) -> List[Event]:
        """Retrieve recent events across all entities. workspace_id=None means
        unscoped (admin/internal callers only — route handlers must pass the
        caller's own workspace_id for non-admin keys)."""
        q = db.query(Event)
        if workspace_id is not None:
            linked = db.query(EntityWorkspace.entity_id).filter(
                EntityWorkspace.workspace_id == workspace_id
            )
            q = q.filter(Event.entity_id.in_(linked))
        return q.order_by(Event.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_all_entity_ids(db: Session, workspace_id: Optional[str] = None) -> List[str]:
        """Get list of unique entity IDs. workspace_id=None means unscoped
        (admin/internal callers only)."""
        if workspace_id is not None:
            result = db.query(EntityWorkspace.entity_id).filter(
                EntityWorkspace.workspace_id == workspace_id
            ).distinct().all()
        else:
            result = db.query(Event.entity_id).distinct().all()
        return [row[0] for row in result]
