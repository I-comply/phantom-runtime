from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime, timezone
import uuid
import hashlib
import json
from app.core.database import Base

# Corruption-detecting event chain. NOT tamper-evident: event_hash is an
# unkeyed SHA-256 over the event's own fields, so anyone with write access to
# this table can recompute every hash and produce a self-consistent forgery.
# Catches accidental corruption/reordering, not a privileged attacker. For an
# actually tamper-evident, HMAC-keyed ledger (resists DB-write access without
# the master key), see https://github.com/I-comply/Agent-Trust-Layer
# (atl/ledger.py) — this engine is a separate, unrelated implementation, not
# a lighter version of that one.
class EventV3(Base):
    __tablename__ = "events_v3"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    entity_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)

    # Chain fields (corruption detection only; see class docstring)
    event_hash = Column(String(64), unique=True, nullable=False, index=True)
    previous_hash = Column(String(64), nullable=True)
    block_index = Column(Integer, nullable=False)
    schema_version = Column(Integer, default=1)
    priority_level = Column(SQLEnum('normal', 'high', 'critical', name='priority_enum'), default='normal')
    source = Column(SQLEnum('api', 'agent', 'system', 'external', name='source_enum'), default='api')

    # Metadata
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('workspaces.id'), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_by = Column(String, nullable=True)  # User/API key identifier

    # Caller-supplied, currently unverified: stored as given, never checked
    # against anything by EventEngineV3 or verify_chain_integrity(). Not an
    # enforced control until something actually validates them — don't rely
    # on either column for tamper detection or replay protection yet.
    hmac_signature = Column(String, nullable=True)
    nonce = Column(String, nullable=True)

    __table_args__ = (
        Index('idx_entity_block', 'entity_id', 'block_index'),
        Index('idx_tenant_entity', 'tenant_id', 'entity_id'),
        Index('idx_priority_created', 'priority_level', 'created_at'),
    )

    @staticmethod
    def compute_hash(entity_id: str, event_type: str, payload: dict,
                     block_index: int, previous_hash: str = None) -> str:
        """Deterministic, unkeyed chain hash — corruption/reordering detection
        only, see class docstring for what this does not guarantee."""
        data = f"{entity_id}:{event_type}:{json.dumps(payload, sort_keys=True)}:{block_index}:{previous_hash or ''}"
        return hashlib.sha256(data.encode()).hexdigest()

# RBAC Tables
class Role(Base):
    __tablename__ = "roles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(SQLEnum('admin', 'agent', 'viewer', 'system', name='role_enum'), unique=True)
    permissions = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class APIKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('workspaces.id'), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey('roles.id'), nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)

# Strategy Execution
class Strategy(Base):
    __tablename__ = "strategies"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('workspaces.id'), nullable=True)
    name = Column(String, nullable=False)
    strategy_type = Column(String, nullable=False)  # arbitrage, liquidity, yield, anomaly
    code = Column(Text, nullable=False)
    config = Column(JSONB, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class StrategyExecution(Base):
    __tablename__ = "strategy_executions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey('strategies.id'), nullable=False)
    entity_id = Column(String, nullable=False)
    input_events = Column(JSONB)  # List of event IDs consumed
    output_events = Column(JSONB)  # List of event IDs produced
    status = Column(SQLEnum('pending', 'running', 'completed', 'failed', name='exec_status_enum'))
    result = Column(JSONB)
    error = Column(Text)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime)

# DeFi Entities
class DeFiEntity(Base):
    __tablename__ = "defi_entities"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('workspaces.id'), nullable=True)
    entity_id = Column(String, unique=True, nullable=False, index=True)
    entity_type = Column(SQLEnum('wallet', 'contract', 'liquidity_pool', name='defi_entity_enum'))
    entity_metadata = Column(JSONB, default=dict)  # Renamed from metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# Financial Event Types
class FinancialEvent(Base):
    __tablename__ = "financial_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_v3_id = Column(Integer, ForeignKey('events_v3.id'), nullable=False)
    entity_id = Column(String, nullable=False, index=True)
    
    # Financial event types
    event_subtype = Column(SQLEnum(
        'ASSET_MINT', 'ASSET_TRANSFER', 'POSITION_OPEN', 'POSITION_CLOSE',
        'LIQUIDITY_ADD', 'LIQUIDITY_REMOVE', 'SWAP_EXECUTED', 'PRICE_FEED_UPDATE',
        name='financial_event_enum'
    ))
    
    asset = Column(String)
    amount = Column(String)  # String to avoid precision loss
    price = Column(String)
    counterparty = Column(String)  # Other entity involved
    event_metadata = Column(JSONB, default=dict)  # Renamed from metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_financial_entity_type', 'entity_id', 'event_subtype'),
    )

# Async Queue
class EventQueue(Base):
    __tablename__ = "event_queue"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String, nullable=False)
    event_data = Column(JSONB, nullable=False)
    priority = Column(SQLEnum('normal', 'high', 'critical', name='queue_priority_enum'), default='normal')
    status = Column(SQLEnum('pending', 'processing', 'completed', 'failed', name='queue_status_enum'), default='pending')
    retry_count = Column(Integer, default=0)
    error = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime)
    
    __table_args__ = (
        Index('idx_queue_status_priority', 'status', 'priority', 'created_at'),
    )
