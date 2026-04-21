"""
Phantom Runtime - Observability Stack
Prometheus Metrics + Grafana Dashboards + OpenTelemetry Tracing + Structured Logging
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import json
import logging
from functools import wraps

# ============================================================
# 1. PROMETHEUS METRICS
# ============================================================

from prometheus_client import Counter, Histogram, Gauge, Summary, CollectorRegistry

# Create registry
registry = CollectorRegistry()

# Counter metrics
events_created_total = Counter(
    'phantom_events_created_total',
    'Total events created',
    ['entity_type'],
    registry=registry
)

events_processed_total = Counter(
    'phantom_events_processed_total',
    'Total events processed',
    ['event_type'],
    registry=registry
)

reconstruction_failures_total = Counter(
    'phantom_reconstruction_failures_total',
    'Total state reconstruction failures',
    registry=registry
)

# Histogram metrics (response times)
event_creation_duration_ms = Histogram(
    'phantom_event_creation_duration_ms',
    'Event creation duration in milliseconds',
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
    registry=registry
)

state_reconstruction_duration_ms = Histogram(
    'phantom_state_reconstruction_duration_ms',
    'State reconstruction duration in milliseconds',
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
    registry=registry
)

api_request_duration_ms = Histogram(
    'phantom_api_request_duration_ms',
    'API request duration in milliseconds',
    ['method', 'endpoint'],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
    registry=registry
)

# Gauge metrics (current state)
active_entities = Gauge(
    'phantom_active_entities',
    'Number of active entities',
    registry=registry
)

event_log_size_bytes = Gauge(
    'phantom_event_log_size_bytes',
    'Total event log size in bytes',
    registry=registry
)

pending_events_queue = Gauge(
    'phantom_pending_events_queue',
    'Number of pending events in queue',
    registry=registry
)

db_connection_pool_available = Gauge(
    'phantom_db_connection_pool_available',
    'Available database connections',
    registry=registry
)

# Summary metrics
snapshot_creation_duration_seconds = Summary(
    'phantom_snapshot_creation_duration_seconds',
    'Snapshot creation duration in seconds',
    registry=registry
)

# ============================================================
# 2. STRUCTURED LOGGING
# ============================================================

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

@dataclass
class LogEntry:
    timestamp: str
    level: str
    message: str
    service: str = "phantom-runtime"
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    user_id: Optional[str] = None
    entity_id: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    tags: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_json(self) -> str:
        """Convert to JSON"""
        return json.dumps({
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "service": self.service,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "user_id": self.user_id,
            "entity_id": self.entity_id,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "tags": self.tags or {},
            "metadata": self.metadata or {}
        })

class StructuredLogger:
    """Structured JSON logger"""
    
    def __init__(self, service_name: str = "phantom-runtime"):
        self.service_name = service_name
        self.logger = logging.getLogger(service_name)
    
    def log(self, level: LogLevel, message: str, **kwargs) -> LogEntry:
        """Log structured message"""
        entry = LogEntry(
            timestamp=datetime.utcnow().isoformat(),
            level=level.value,
            message=message,
            service=self.service_name,
            **kwargs
        )
        
        # Output as JSON
        print(entry.to_json())
        
        return entry
    
    def debug(self, message: str, **kwargs):
        return self.log(LogLevel.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        return self.log(LogLevel.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        return self.log(LogLevel.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        return self.log(LogLevel.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        return self.log(LogLevel.CRITICAL, message, **kwargs)

logger = StructuredLogger()

# ============================================================
# 3. OPENTELEMETRY TRACING
# ============================================================

from dataclasses import field

@dataclass
class TraceSpan:
    """OpenTelemetry-style span"""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    operation_name: str
    start_time_ms: float
    end_time_ms: Optional[float] = None
    status: str = "UNSET"  # UNSET, OK, ERROR
    error_message: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict] = field(default_factory=list)
    
    def duration_ms(self) -> Optional[float]:
        if self.end_time_ms:
            return self.end_time_ms - self.start_time_ms
        return None
    
    def end(self, status: str = "OK", error: Optional[str] = None):
        """End span"""
        self.end_time_ms = time.time() * 1000
        self.status = status
        self.error_message = error
        
        logger.info(
            f"span_ended",
            trace_id=self.trace_id,
            span_id=self.span_id,
            operation=self.operation_name,
            duration_ms=self.duration_ms(),
            status=status
        )

class TracingContext:
    """Tracing context manager"""
    
    def __init__(self):
        self.spans: List[TraceSpan] = []
        self.current_span: Optional[TraceSpan] = None
    
    def start_span(self, operation_name: str, trace_id: str, attributes: Optional[Dict] = None) -> TraceSpan:
        """Start a trace span"""
        parent_span_id = self.current_span.span_id if self.current_span else None
        span_id = f"span_{len(self.spans)}"
        
        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            start_time_ms=time.time() * 1000,
            attributes=attributes or {}
        )
        
        self.spans.append(span)
        old_span = self.current_span
        self.current_span = span
        
        logger.info(
            "span_started",
            trace_id=trace_id,
            span_id=span_id,
            operation=operation_name,
            parent_span_id=parent_span_id
        )
        
        return span
    
    def end_span(self, status: str = "OK", error: Optional[str] = None):
        """End current span"""
        if self.current_span:
            self.current_span.end(status, error)

def traced(operation_name: str):
    """Decorator for tracing"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            trace_id = f"trace_{int(time.time() * 1000)}"
            ctx = TracingContext()
            
            try:
                span = ctx.start_span(operation_name, trace_id)
                result = func(*args, **kwargs)
                ctx.end_span("OK")
                return result
            except Exception as e:
                ctx.end_span("ERROR", str(e))
                raise
        
        return wrapper
    return decorator

# ============================================================
# 4. METRICS COLLECTION
# ============================================================

class MetricsCollector:
    """Collect and expose metrics"""
    
    @staticmethod
    def record_event_created(entity_type: str):
        """Record event creation"""
        events_created_total.labels(entity_type=entity_type).inc()
    
    @staticmethod
    def record_event_processed(event_type: str):
        """Record event processing"""
        events_processed_total.labels(event_type=event_type).inc()
    
    @staticmethod
    def record_event_creation_time(duration_ms: float):
        """Record event creation time"""
        event_creation_duration_ms.observe(duration_ms)
    
    @staticmethod
    def record_reconstruction_time(duration_ms: float):
        """Record state reconstruction time"""
        state_reconstruction_duration_ms.observe(duration_ms)
    
    @staticmethod
    def record_api_request_time(method: str, endpoint: str, duration_ms: float):
        """Record API request time"""
        api_request_duration_ms.labels(method=method, endpoint=endpoint).observe(duration_ms)
    
    @staticmethod
    def set_active_entities(count: int):
        """Set active entities count"""
        active_entities.set(count)
    
    @staticmethod
    def set_event_log_size(size_bytes: int):
        """Set event log size"""
        event_log_size_bytes.set(size_bytes)
    
    @staticmethod
    def set_pending_events_queue(count: int):
        """Set pending events count"""
        pending_events_queue.set(count)
    
    @staticmethod
    def record_snapshot_creation_time(duration_seconds: float):
        """Record snapshot creation time"""
        snapshot_creation_duration_seconds.observe(duration_seconds)
    
    @staticmethod
    def get_metrics() -> Dict:
        """Get all metrics"""
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return {
            "metrics": generate_latest(registry).decode('utf-8'),
            "content_type": CONTENT_TYPE_LATEST
        }

# ============================================================
# 5. GRAFANA DASHBOARD CONFIGURATION
# ============================================================

GRAFANA_DASHBOARD_JSON = {
    "dashboard": {
        "title": "Phantom Runtime - Observability",
        "tags": ["phantom", "event-sourcing"],
        "timezone": "browser",
        "panels": [
            {
                "id": 1,
                "title": "Events Created Per Second",
                "type": "graph",
                "targets": [
                    {
                        "expr": "rate(phantom_events_created_total[1m])",
                        "legendFormat": "{{entity_type}}"
                    }
                ]
            },
            {
                "id": 2,
                "title": "Event Creation Duration (p99)",
                "type": "graph",
                "targets": [
                    {
                        "expr": "histogram_quantile(0.99, phantom_event_creation_duration_ms)",
                        "legendFormat": "P99"
                    }
                ]
            },
            {
                "id": 3,
                "title": "State Reconstruction Duration (p99)",
                "type": "graph",
                "targets": [
                    {
                        "expr": "histogram_quantile(0.99, phantom_state_reconstruction_duration_ms)",
                        "legendFormat": "P99"
                    }
                ]
            },
            {
                "id": 4,
                "title": "API Request Duration (p95)",
                "type": "graph",
                "targets": [
                    {
                        "expr": "histogram_quantile(0.95, phantom_api_request_duration_ms)",
                        "legendFormat": "{{method}} {{endpoint}}"
                    }
                ]
            },
            {
                "id": 5,
                "title": "Active Entities",
                "type": "gauge",
                "targets": [
                    {
                        "expr": "phantom_active_entities",
                        "legendFormat": "Entities"
                    }
                ]
            },
            {
                "id": 6,
                "title": "Event Log Size (MB)",
                "type": "gauge",
                "targets": [
                    {
                        "expr": "phantom_event_log_size_bytes / 1024 / 1024",
                        "legendFormat": "Size"
                    }
                ]
            },
            {
                "id": 7,
                "title": "Pending Events Queue",
                "type": "gauge",
                "targets": [
                    {
                        "expr": "phantom_pending_events_queue",
                        "legendFormat": "Pending"
                    }
                ]
            },
            {
                "id": 8,
                "title": "Reconstruction Failures",
                "type": "counter",
                "targets": [
                    {
                        "expr": "phantom_reconstruction_failures_total",
                        "legendFormat": "Failures"
                    }
                ]
            },
            {
                "id": 9,
                "title": "DB Connection Pool Available",
                "type": "gauge",
                "targets": [
                    {
                        "expr": "phantom_db_connection_pool_available",
                        "legendFormat": "Available"
                    }
                ]
            },
            {
                "id": 10,
                "title": "Snapshot Creation Time (p50)",
                "type": "graph",
                "targets": [
                    {
                        "expr": "histogram_quantile(0.5, phantom_snapshot_creation_duration_seconds)",
                        "legendFormat": "P50"
                    }
                ]
            }
        ]
    }
}

# ============================================================
# 6. ALERTING RULES
# ============================================================

PROMETHEUS_ALERTS = """
# Phantom Runtime Alerting Rules

groups:
  - name: phantom-runtime
    interval: 30s
    rules:
      - alert: HighEventCreationLatency
        expr: histogram_quantile(0.99, phantom_event_creation_duration_ms) > 100
        for: 5m
        annotations:
          summary: "High event creation latency ({{ $value }}ms)"
      
      - alert: HighReconstructionFailureRate
        expr: rate(phantom_reconstruction_failures_total[5m]) > 0.01
        for: 5m
        annotations:
          summary: "High reconstruction failure rate"
      
      - alert: HighEventLogSize
        expr: phantom_event_log_size_bytes / 1024 / 1024 / 1024 > 10
        for: 5m
        annotations:
          summary: "Event log exceeds 10 GB"
      
      - alert: DBConnectionPoolExhausted
        expr: phantom_db_connection_pool_available < 5
        for: 2m
        annotations:
          summary: "DB connection pool running low"
      
      - alert: HighPendingEventsQueue
        expr: phantom_pending_events_queue > 1000
        for: 5m
        annotations:
          summary: "High number of pending events in queue"
      
      - alert: HighAPILatency
        expr: histogram_quantile(0.95, phantom_api_request_duration_ms) > 500
        for: 5m
        annotations:
          summary: "API latency exceeds 500ms"
"""

# ============================================================
# 7. OBSERVABILITY EXAMPLE
# ============================================================

class ObservabilityDemo:
    """Demonstrate observability features"""
    
    @staticmethod
    @traced("event_creation")
    def create_event(entity_id: str, event_type: str, payload: Dict) -> str:
        """Create event with tracing and metrics"""
        start = time.time()
        
        try:
            logger.info(
                "Creating event",
                entity_id=entity_id,
                event_type=event_type
            )
            
            # Simulate event creation
            time.sleep(0.01)
            
            duration_ms = (time.time() - start) * 1000
            
            # Record metrics
            MetricsCollector.record_event_created(entity_type="user")
            MetricsCollector.record_event_creation_time(duration_ms)
            
            event_id = f"event_{int(time.time() * 1000)}"
            
            logger.info(
                "Event created successfully",
                entity_id=entity_id,
                event_id=event_id,
                duration_ms=duration_ms
            )
            
            return event_id
        
        except Exception as e:
            logger.error(
                "Event creation failed",
                entity_id=entity_id,
                error=str(e)
            )
            raise
    
    @staticmethod
    @traced("state_reconstruction")
    def reconstruct_state(events: List[Dict]) -> Dict:
        """Reconstruct state with tracing and metrics"""
        start = time.time()
        
        try:
            logger.info(
                "Reconstructing state",
                event_count=len(events)
            )
            
            state = {}
            for event in events:
                if event.get("type") == "init":
                    state = event.get("payload", {}).copy()
                elif event.get("type") == "update":
                    state.update(event.get("payload", {}))
            
            duration_ms = (time.time() - start) * 1000
            
            # Record metrics
            MetricsCollector.record_reconstruction_time(duration_ms)
            
            logger.info(
                "State reconstruction completed",
                event_count=len(events),
                duration_ms=duration_ms
            )
            
            return state
        
        except Exception as e:
            logger.error(
                "State reconstruction failed",
                error=str(e),
                event_count=len(events)
            )
            raise

if __name__ == "__main__":
    # Demo
    ObservabilityDemo.create_event("user_1", "init", {"name": "Alice"})
    ObservabilityDemo.reconstruct_state([
        {"type": "init", "payload": {"balance": 100}},
        {"type": "update", "payload": {"balance": 150}}
    ])
    
    # Get metrics
    print("\n=== Prometheus Metrics ===")
    print(MetricsCollector.get_metrics()["metrics"][:500])
    
    # Get Grafana dashboard config
    print("\n=== Grafana Dashboard Panels ===")
    print(json.dumps(GRAFANA_DASHBOARD_JSON["dashboard"]["panels"][:2], indent=2))
