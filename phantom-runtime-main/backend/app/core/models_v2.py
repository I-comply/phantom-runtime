from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Index, JSON
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from app.core.database import Base
from app.core.models import Event

# Multi-Tenancy: Workspaces
class Workspace(Base):
    __tablename__ = "workspaces"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    api_key = Column(String, unique=True, nullable=False, index=True)
    settings = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    
    entities = relationship("EntityWorkspace", back_populates="workspace")

# Entity-Workspace Mapping
class EntityWorkspace(Base):
    __tablename__ = "entity_workspaces"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey('workspaces.id'), nullable=False)
    entity_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    workspace = relationship("Workspace", back_populates="entities")
    
    __table_args__ = (
        Index('idx_workspace_entity', 'workspace_id', 'entity_id'),
    )

# Snapshot System
class Snapshot(Base):
    __tablename__ = "snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String, nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey('workspaces.id'), nullable=True)
    snapshot_number = Column(Integer, nullable=False)
    event_count = Column(Integer, nullable=False)
    last_event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    state_data = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_entity_snapshot', 'entity_id', 'snapshot_number'),
        Index('idx_workspace_snapshot', 'workspace_id', 'entity_id'),
    )

# Plugin System
class Plugin(Base):
    __tablename__ = "plugins"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey('workspaces.id'), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    plugin_type = Column(String, nullable=False)  # compute, trigger, scheduled
    code = Column(Text, nullable=False)
    config = Column(JSONB, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class PluginExecution(Base):
    __tablename__ = "plugin_executions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plugin_id = Column(UUID(as_uuid=True), ForeignKey('plugins.id'), nullable=False)
    entity_id = Column(String, nullable=False)
    status = Column(String, nullable=False)  # pending, running, completed, failed
    result = Column(JSONB)
    error = Column(Text)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime)
    
    __table_args__ = (
        Index('idx_plugin_exec', 'plugin_id', 'entity_id', 'started_at'),
    )

# DeFi Event Abstractions
class DeFiEvent(Base):
    __tablename__ = "defi_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey('workspaces.id'), nullable=True)
    entity_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False)  # deposit, withdraw, trade, transfer, stake, unstake
    asset = Column(String)  # BTC, ETH, USD, etc.
    amount = Column(String)  # Use string to avoid float precision issues
    price = Column(String)  # Price at event time (optional)
    event_metadata = Column(JSONB, default=dict)  # Renamed from metadata to avoid SQLAlchemy conflict
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Link to core event system
    core_event_id = Column(Integer, ForeignKey('events.id'))
    
    __table_args__ = (
        Index('idx_defi_entity_type', 'entity_id', 'event_type', 'created_at'),
    )

# Event Schema Versioning
class EventSchema(Base):
    __tablename__ = "event_schemas"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String, nullable=False, unique=True)
    version = Column(Integer, nullable=False)
    schema_definition = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# Async Job Tracking
class AsyncJob(Base):
    __tablename__ = "async_jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(String, nullable=False)  # event_batch, snapshot_create, plugin_exec
    status = Column(String, nullable=False)  # pending, processing, completed, failed
    payload = Column(JSONB)
    result = Column(JSONB)
    error = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime)
    
    __table_args__ = (
        Index('idx_job_status', 'status', 'created_at'),
    )
