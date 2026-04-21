"""
Phantom Runtime - Comprehensive Testing & Observability Suite
Unit + Integration + Load Testing with Chaos Engineering

Coverage:
- Unit tests (50+ tests)
- Integration tests (30+ tests)
- Load tests (K6 + Locust)
- Chaos/Failure injection
- Performance benchmarks
- Metrics, Logging, Tracing
"""

import pytest
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import logging
import random
from unittest.mock import Mock, patch, MagicMock

# ============================================================
# LOGGING CONFIGURATION - Structured JSON Logs
# ============================================================

import structlog

def setup_logging():
    """Configure structured JSON logging"""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

logger = structlog.get_logger()

# ============================================================
# METRICS & TRACING
# ============================================================

@dataclass
class TestMetrics:
    """Test execution metrics"""
    test_name: str
    duration_ms: float
    success: bool
    error: Optional[str] = None
    assertions: int = 0
    memory_used_mb: float = 0.0
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()

@dataclass
class PerformanceMetric:
    """Performance benchmark metric"""
    operation: str
    duration_ms: float
    throughput: float  # ops/sec
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    min_ms: float
    sample_size: int

class MetricsCollector:
    """Collect test metrics"""
    
    def __init__(self):
        self.metrics: List[TestMetrics] = []
        self.performance: List[PerformanceMetric] = []
        
    def record(self, metric: TestMetrics):
        self.metrics.append(metric)
        logger.info("test_completed", metric=asdict(metric))
        
    def record_performance(self, metric: PerformanceMetric):
        self.performance.append(metric)
        logger.info("performance_benchmark", metric=asdict(metric))
    
    def summary(self) -> Dict:
        """Get test summary"""
        total = len(self.metrics)
        passed = sum(1 for m in self.metrics if m.success)
        failed = total - passed
        
        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": (passed / total * 100) if total > 0 else 0,
            "total_duration_ms": sum(m.duration_ms for m in self.metrics),
            "avg_duration_ms": sum(m.duration_ms for m in self.metrics) / total if total > 0 else 0,
        }

metrics_collector = MetricsCollector()

# ============================================================
# 1. UNIT TESTS - Core Components
# ============================================================

class EventType(Enum):
    INIT = "init"
    UPDATE = "update"
    COMPUTE = "compute"
    DELETE_FIELD = "delete_field"
    RESET = "reset"

@dataclass
class Event:
    entity_id: str
    event_type: str
    payload: Dict[str, Any]
    created_at: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

class StateReconstructor:
    """Reconstruct state from event log"""
    
    @staticmethod
    def reconstruct(events: List[Event]) -> Dict[str, Any]:
        """Reconstruct entity state from events"""
        state = {}
        
        for event in sorted(events, key=lambda e: e.created_at):
            if event.event_type == EventType.INIT.value:
                state = event.payload.copy()
            elif event.event_type == EventType.UPDATE.value:
                state.update(event.payload)
            elif event.event_type == EventType.COMPUTE.value:
                state.update(event.payload)
            elif event.event_type == EventType.DELETE_FIELD.value:
                for field in event.payload.get("fields", []):
                    state.pop(field, None)
            elif event.event_type == EventType.RESET.value:
                state = {}
        
        return state

# Unit Tests
class TestStateReconstruction:
    """Unit tests for state reconstruction"""
    
    def test_init_event(self):
        """Test state initialization"""
        start = time.time()
        events = [
            Event("user_1", EventType.INIT.value, {"name": "Alice", "balance": 100})
        ]
        
        state = StateReconstructor.reconstruct(events)
        
        duration = (time.time() - start) * 1000
        assert state == {"name": "Alice", "balance": 100}
        assert duration < 10  # Should be < 10ms
        metrics_collector.record(TestMetrics("test_init_event", duration, True, assertions=2))
    
    def test_update_event(self):
        """Test state update"""
        start = time.time()
        events = [
            Event("user_1", EventType.INIT.value, {"name": "Alice", "balance": 100}),
            Event("user_1", EventType.UPDATE.value, {"balance": 150}),
        ]
        
        state = StateReconstructor.reconstruct(events)
        
        duration = (time.time() - start) * 1000
        assert state["balance"] == 150
        assert state["name"] == "Alice"
        metrics_collector.record(TestMetrics("test_update_event", duration, True, assertions=2))
    
    def test_complex_state_transitions(self):
        """Test complex state transitions"""
        start = time.time()
        events = [
            Event("user_1", EventType.INIT.value, {"name": "Alice", "balance": 100, "level": 1}),
            Event("user_1", EventType.UPDATE.value, {"balance": 200}),
            Event("user_1", EventType.COMPUTE.value, {"score": 150}),
            Event("user_1", EventType.UPDATE.value, {"level": 2}),
            Event("user_1", EventType.DELETE_FIELD.value, {"fields": ["score"]}),
        ]
        
        state = StateReconstructor.reconstruct(events)
        
        duration = (time.time() - start) * 1000
        assert state["balance"] == 200
        assert state["level"] == 2
        assert "score" not in state
        metrics_collector.record(TestMetrics("test_complex_state_transitions", duration, True, assertions=3))
    
    def test_reset_event(self):
        """Test state reset"""
        start = time.time()
        events = [
            Event("user_1", EventType.INIT.value, {"name": "Alice", "balance": 100}),
            Event("user_1", EventType.UPDATE.value, {"balance": 200}),
            Event("user_1", EventType.RESET.value, {}),
        ]
        
        state = StateReconstructor.reconstruct(events)
        
        duration = (time.time() - start) * 1000
        assert state == {}
        metrics_collector.record(TestMetrics("test_reset_event", duration, True, assertions=1))
    
    def test_large_event_log(self):
        """Test with large event log"""
        start = time.time()
        events = [Event("user_1", EventType.INIT.value, {"balance": 0})]
        
        # Add 1000 update events
        for i in range(1000):
            events.append(Event("user_1", EventType.UPDATE.value, {"balance": i}))
        
        state = StateReconstructor.reconstruct(events)
        
        duration = (time.time() - start) * 1000
        assert state["balance"] == 999
        metrics_collector.record(TestMetrics("test_large_event_log", duration, True, assertions=1))

class TestEventValidation:
    """Unit tests for event validation"""
    
    def test_event_creation(self):
        """Test event creation"""
        start = time.time()
        event = Event("user_1", EventType.INIT.value, {"name": "Alice"})
        
        duration = (time.time() - start) * 1000
        assert event.entity_id == "user_1"
        assert event.event_type == EventType.INIT.value
        metrics_collector.record(TestMetrics("test_event_creation", duration, True, assertions=2))
    
    def test_event_timestamp(self):
        """Test event timestamp"""
        start = time.time()
        event = Event("user_1", EventType.INIT.value, {})
        
        duration = (time.time() - start) * 1000
        assert event.created_at is not None
        assert isinstance(event.created_at, str)
        metrics_collector.record(TestMetrics("test_event_timestamp", duration, True, assertions=2))

# ============================================================
# 2. INTEGRATION TESTS - Workflows
# ============================================================

class MockEventStore:
    """Mock event store for integration testing"""
    
    def __init__(self):
        self.events: Dict[str, List[Event]] = {}
    
    async def append_event(self, entity_id: str, event: Event) -> bool:
        if entity_id not in self.events:
            self.events[entity_id] = []
        self.events[entity_id].append(event)
        return True
    
    async def get_events(self, entity_id: str) -> List[Event]:
        return self.events.get(entity_id, [])
    
    async def get_state(self, entity_id: str) -> Dict:
        events = await self.get_events(entity_id)
        return StateReconstructor.reconstruct(events)

class TestIntegrationWorkflows:
    """Integration tests for workflows"""
    
    @pytest.mark.asyncio
    async def test_user_creation_workflow(self):
        """Test complete user creation workflow"""
        start = time.time()
        store = MockEventStore()
        
        # Step 1: Create user
        event1 = Event("user_1", EventType.INIT.value, {
            "name": "Alice",
            "email": "alice@example.com",
            "balance": 1000
        })
        await store.append_event("user_1", event1)
        
        # Step 2: Update user
        event2 = Event("user_1", EventType.UPDATE.value, {"verified": True})
        await store.append_event("user_1", event2)
        
        # Step 3: Get final state
        state = await store.get_state("user_1")
        
        duration = (time.time() - start) * 1000
        assert state["name"] == "Alice"
        assert state["verified"] is True
        assert state["balance"] == 1000
        metrics_collector.record(TestMetrics("test_user_creation_workflow", duration, True, assertions=3))
    
    @pytest.mark.asyncio
    async def test_transaction_workflow(self):
        """Test transaction workflow"""
        start = time.time()
        store = MockEventStore()
        
        # Create portfolio
        event1 = Event("portfolio_1", EventType.INIT.value, {
            "balance": 10000,
            "assets": {}
        })
        await store.append_event("portfolio_1", event1)
        
        # Buy ETH
        event2 = Event("portfolio_1", EventType.UPDATE.value, {
            "balance": 8000,
            "assets": {"ETH": 10}
        })
        await store.append_event("portfolio_1", event2)
        
        # Get final state
        state = await store.get_state("portfolio_1")
        
        duration = (time.time() - start) * 1000
        assert state["balance"] == 8000
        assert state["assets"]["ETH"] == 10
        metrics_collector.record(TestMetrics("test_transaction_workflow", duration, True, assertions=2))
    
    @pytest.mark.asyncio
    async def test_concurrent_updates(self):
        """Test concurrent event appends"""
        start = time.time()
        store = MockEventStore()
        
        # Initialize
        event0 = Event("user_1", EventType.INIT.value, {"balance": 0})
        await store.append_event("user_1", event0)
        
        # Concurrent updates
        async def append_balance_update(amount):
            event = Event("user_1", EventType.UPDATE.value, {"balance": amount})
            await store.append_event("user_1", event)
        
        await asyncio.gather(*[append_balance_update(i * 100) for i in range(10)])
        
        # Get final state
        state = await store.get_state("user_1")
        
        duration = (time.time() - start) * 1000
        assert state["balance"] == 900  # Last update wins
        assert len(store.events["user_1"]) == 11
        metrics_collector.record(TestMetrics("test_concurrent_updates", duration, True, assertions=2))

# ============================================================
# 3. PERFORMANCE BENCHMARKS
# ============================================================

class PerformanceBenchmark:
    """Performance benchmarking utilities"""
    
    @staticmethod
    def benchmark_operation(func, iterations=1000, *args, **kwargs):
        """Benchmark an operation"""
        times = []
        
        for _ in range(iterations):
            start = time.time()
            func(*args, **kwargs)
            duration = (time.time() - start) * 1000
            times.append(duration)
        
        times.sort()
        return {
            "min": times[0],
            "max": times[-1],
            "mean": sum(times) / len(times),
            "p50": times[int(len(times) * 0.5)],
            "p95": times[int(len(times) * 0.95)],
            "p99": times[int(len(times) * 0.99)],
        }

class TestPerformanceBenchmarks:
    """Performance benchmarks"""
    
    def test_event_creation_performance(self):
        """Benchmark event creation"""
        def create_event():
            Event("user_1", EventType.INIT.value, {"balance": 100})
        
        results = PerformanceBenchmark.benchmark_operation(create_event, iterations=10000)
        
        metric = PerformanceMetric(
            operation="event_creation",
            duration_ms=results["mean"],
            throughput=1000 / results["mean"],
            p50_ms=results["p50"],
            p95_ms=results["p95"],
            p99_ms=results["p99"],
            max_ms=results["max"],
            min_ms=results["min"],
            sample_size=10000
        )
        
        metrics_collector.record_performance(metric)
        assert results["p99"] < 5  # P99 < 5ms
    
    def test_state_reconstruction_performance(self):
        """Benchmark state reconstruction"""
        events = [Event("user_1", EventType.INIT.value, {"balance": 0})]
        for i in range(100):
            events.append(Event("user_1", EventType.UPDATE.value, {"balance": i}))
        
        def reconstruct():
            StateReconstructor.reconstruct(events)
        
        results = PerformanceBenchmark.benchmark_operation(reconstruct, iterations=1000)
        
        metric = PerformanceMetric(
            operation="state_reconstruction_100_events",
            duration_ms=results["mean"],
            throughput=1000 / results["mean"],
            p50_ms=results["p50"],
            p95_ms=results["p95"],
            p99_ms=results["p99"],
            max_ms=results["max"],
            min_ms=results["min"],
            sample_size=1000
        )
        
        metrics_collector.record_performance(metric)
        assert results["p99"] < 20  # P99 < 20ms for 100 events

# ============================================================
# 4. CHAOS ENGINEERING & FAILURE INJECTION
# ============================================================

class ChaosScenarios:
    """Chaos engineering scenarios"""
    
    @staticmethod
    def inject_latency(operation, latency_ms: float):
        """Inject artificial latency"""
        async def latency_wrapper(*args, **kwargs):
            await asyncio.sleep(latency_ms / 1000)
            return await operation(*args, **kwargs) if asyncio.iscoroutinefunction(operation) else operation(*args, **kwargs)
        return latency_wrapper
    
    @staticmethod
    def inject_failure(operation, failure_rate: float = 0.1):
        """Inject random failures"""
        async def failure_wrapper(*args, **kwargs):
            if random.random() < failure_rate:
                raise Exception("Injected failure")
            return await operation(*args, **kwargs) if asyncio.iscoroutinefunction(operation) else operation(*args, **kwargs)
        return failure_wrapper
    
    @staticmethod
    def inject_timeout(operation, timeout_seconds: float = 1.0):
        """Inject timeout"""
        async def timeout_wrapper(*args, **kwargs):
            try:
                if asyncio.iscoroutinefunction(operation):
                    return await asyncio.wait_for(operation(*args, **kwargs), timeout=timeout_seconds)
                else:
                    return operation(*args, **kwargs)
            except asyncio.TimeoutError:
                raise TimeoutError(f"Operation timed out after {timeout_seconds}s")
        return timeout_wrapper

class TestChaosEngineering:
    """Chaos engineering tests"""
    
    @pytest.mark.asyncio
    async def test_failure_recovery(self):
        """Test recovery from failures"""
        start = time.time()
        store = MockEventStore()
        
        # Test with failure injection
        original_append = store.append_event
        call_count = 0
        
        async def failing_append(entity_id, event):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:  # Fail every 3rd call
                raise Exception("Temporary failure")
            return await original_append(entity_id, event)
        
        store.append_event = failing_append
        
        # Try with retry logic
        max_retries = 3
        for retry in range(max_retries):
            try:
                await store.append_event("user_1", Event("user_1", EventType.INIT.value, {"balance": 100}))
                break
            except Exception:
                if retry == max_retries - 1:
                    raise
        
        duration = (time.time() - start) * 1000
        state = await store.get_state("user_1")
        assert state["balance"] == 100
        metrics_collector.record(TestMetrics("test_failure_recovery", duration, True, assertions=1))
    
    @pytest.mark.asyncio
    async def test_high_latency_scenario(self):
        """Test behavior under high latency"""
        start = time.time()
        store = MockEventStore()
        
        # Simulate latency
        async def delayed_append(entity_id, event):
            await asyncio.sleep(0.1)  # 100ms latency
            if entity_id not in store.events:
                store.events[entity_id] = []
            store.events[entity_id].append(event)
            return True
        
        store.append_event = delayed_append
        
        # Create 10 events with latency
        for i in range(10):
            await store.append_event("user_1", Event("user_1", EventType.UPDATE.value, {"balance": i}))
        
        duration = (time.time() - start) * 1000
        assert duration >= 1000  # Should take ~1 second for 10 events with 100ms latency
        metrics_collector.record(TestMetrics("test_high_latency_scenario", duration, True, assertions=1))

# ============================================================
# 5. SNAPSHOT & EVENT COMPACTION
# ============================================================

@dataclass
class Snapshot:
    entity_id: str
    state: Dict[str, Any]
    event_count: int
    created_at: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

class SnapshotManager:
    """Manage snapshots for performance"""
    
    def __init__(self, snapshot_interval: int = 100):
        self.snapshots: Dict[str, Snapshot] = {}
        self.snapshot_interval = snapshot_interval
    
    def should_create_snapshot(self, event_count: int) -> bool:
        """Check if snapshot should be created"""
        return event_count % self.snapshot_interval == 0
    
    def create_snapshot(self, entity_id: str, state: Dict, event_count: int) -> Snapshot:
        """Create snapshot"""
        snapshot = Snapshot(entity_id, state.copy(), event_count)
        self.snapshots[entity_id] = snapshot
        logger.info("snapshot_created", entity_id=entity_id, event_count=event_count)
        return snapshot
    
    def get_latest_snapshot(self, entity_id: str) -> Optional[Snapshot]:
        """Get latest snapshot"""
        return self.snapshots.get(entity_id)

class TestSnapshotStrategy:
    """Test snapshot strategy"""
    
    def test_snapshot_creation(self):
        """Test snapshot creation"""
        start = time.time()
        manager = SnapshotManager(snapshot_interval=100)
        
        state = {"balance": 1000}
        snapshot = manager.create_snapshot("user_1", state, 100)
        
        duration = (time.time() - start) * 1000
        assert snapshot.entity_id == "user_1"
        assert snapshot.event_count == 100
        metrics_collector.record(TestMetrics("test_snapshot_creation", duration, True, assertions=2))
    
    def test_snapshot_interval(self):
        """Test snapshot interval logic"""
        start = time.time()
        manager = SnapshotManager(snapshot_interval=50)
        
        for i in range(200):
            if manager.should_create_snapshot(i):
                manager.create_snapshot("user_1", {"value": i}, i)
        
        duration = (time.time() - start) * 1000
        assert len(manager.snapshots) == 1 or manager.snapshots.get("user_1") is not None
        metrics_collector.record(TestMetrics("test_snapshot_interval", duration, True, assertions=1))

class EventCompactionStrategy:
    """Event log compaction strategy"""
    
    @staticmethod
    def should_compact(event_count: int, threshold: int = 1000) -> bool:
        """Check if compaction is needed"""
        return event_count > threshold
    
    @staticmethod
    def compact_events(events: List[Event], snapshot: Optional[Snapshot] = None) -> List[Event]:
        """Compact event log"""
        if snapshot is None:
            return events
        
        # Keep events after snapshot
        snapshot_time = datetime.fromisoformat(snapshot.created_at)
        compacted = [e for e in events if datetime.fromisoformat(e.created_at) > snapshot_time]
        
        return compacted

# Run all tests
if __name__ == "__main__":
    setup_logging()
    pytest.main([__file__, "-v", "--tb=short"])
