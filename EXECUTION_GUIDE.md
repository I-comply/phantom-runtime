# Phantom Runtime - Complete Test & Observability Execution Guide

**Ready to run all tests, benchmarks, and monitoring**

---

## 🚀 QUICK START (10 minutes)

### Step 1: Install Dependencies

```bash
# Python testing framework
pip install -r requirements-testing.txt

# K6 load testing (macOS)
brew install k6

# Or Docker-based (any OS)
docker pull loadimpact/k6:latest
```

### Step 2: Start Monitoring Stack

```bash
# Start all monitoring services
docker-compose -f docker-compose.monitoring.yml up -d

# Verify services
docker ps | grep phantom

# Access dashboards
echo "Prometheus: http://localhost:9090"
echo "Grafana: http://localhost:3000 (admin/phantom_admin)"
echo "Jaeger: http://localhost:16686"
echo "Loki: http://localhost:3100"
```

### Step 3: Run All Tests

```bash
# Run unit + integration tests
python -m pytest tests/test_suite.py -v --tb=short

# Expected: 80+ tests pass in <60 seconds
```

### Step 4: Run Load Tests

```bash
# K6 load test (6-minute execution)
k6 run tests/load-tests-k6.js --vus 100 --duration 6m

# Or with Docker
docker run -i loadimpact/k6 run - < tests/load-tests-k6.js
```

### Step 5: View Results

```bash
# View metrics in Grafana
open http://localhost:3000

# View traces in Jaeger
open http://localhost:16686

# View logs in Loki
# (Query: {job="phantom-runtime"}
```

---

## 📊 DETAILED EXECUTION PLAN

### Phase 1: Pre-Flight Checks (5 minutes)

```bash
# 1. Check Python
python3 --version  # Requires 3.9+

# 2. Check Docker
docker --version
docker-compose --version

# 3. Check K6
k6 version

# 4. Verify network ports free
lsof -i :9090,3000,9093,3100,16686  # Should be empty

# 5. Check disk space
df -h | grep /  # Need 10+ GB

echo "✅ Pre-flight checks passed"
```

### Phase 2: Monitoring Stack Setup (5 minutes)

```bash
cd phantom-runtime

# 1. Create monitoring configs
mkdir -p observability

# 2. Verify Docker Compose config
docker-compose -f docker-compose.monitoring.yml config > /dev/null

# 3. Start monitoring stack
docker-compose -f docker-compose.monitoring.yml up -d

# 4. Wait for services
sleep 30

# 5. Check service health
docker-compose -f docker-compose.monitoring.yml ps

# Expected all services: Up (healthy)
```

### Phase 3: Unit & Integration Tests (30-60 seconds)

```bash
# Run all tests
python -m pytest tests/test_suite.py -v --tb=short -x

# Expected output:
# ============ test session starts ============
# tests/test_suite.py::TestStateReconstruction::test_init_event PASSED
# tests/test_suite.py::TestStateReconstruction::test_update_event PASSED
# ... (80+ more tests)
# ============ 80+ passed in 45s ============

# Breakdown:
# Unit Tests: 50+ ✓
# Integration Tests: 30+ ✓
# Benchmark Tests: 5+ ✓
# Chaos Tests: 5+ ✓
```

### Phase 4: Performance Benchmarks (5 minutes)

```bash
# Extract benchmark results from tests
python -m pytest tests/test_suite.py::TestPerformanceBenchmarks -v

# Expected results:
# Event Creation:
#   Throughput: 500+ ops/sec
#   P50: 5ms, P95: 25ms, P99: 100ms ✓

# State Reconstruction (100 events):
#   Throughput: 200+ ops/sec  
#   P50: 8ms, P95: 50ms, P99: 150ms ✓

# API Request:
#   Throughput: 100+ ops/sec
#   P50: 15ms, P95: 150ms, P99: 500ms ✓
```

### Phase 5: Load Testing (6+ minutes)

```bash
# Start backend service (if not running)
python -m phantom_runtime.app &

# Wait for startup
sleep 5

# Run K6 load test
k6 run tests/load-tests-k6.js

# Execution stages:
# Stage 1: Ramp 0→10 users (30s)
# Stage 2: Ramp 10→50 users (90s)
# Stage 3: Sustained 50→100 users (120s)
# Stage 4: Burst spike 100→200 users (30s)
# Stage 5: Back to 100 users (120s)
# Stage 6: Ramp down 100→0 (30s)
# Total: ~7 minutes

# Expected results:
# ✓ Total Requests: 10,000+
# ✓ Success Rate: 99%+
# ✓ P95 Latency: <200ms
# ✓ P99 Latency: <500ms
# ✓ Error Rate: <1%
```

### Phase 6: Chaos Engineering (10 minutes)

```bash
# Run chaos tests
python -m pytest tests/test_suite.py::TestChaosEngineering -v

# Scenarios:
# 1. Failure Recovery (10% failure rate)
#    Expected: 99%+ recovery ✓
# 2. High Latency (100ms injected)
#    Expected: All operations complete ✓
# 3. Timeout Scenarios
#    Expected: Proper error handling ✓

# Expected duration: ~10 minutes
```

### Phase 7: Monitor Results (Continuous)

```bash
# Watch metrics in real-time
# Open http://localhost:9090/graph
# View metric: phantom_api_request_duration_ms

# Grafana dashboard
# Open http://localhost:3000
# View: "Phantom Runtime - Observability"

# Jaeger tracing
# Open http://localhost:16686
# Search: Service="phantom-runtime"

# Loki logs
# Query: {job="phantom-runtime"}
# Filter: level="ERROR" (if any)
```

---

## 📈 RESULTS INTERPRETATION

### Success Criteria ✅

```
✓ Unit Tests:            80+ / 80+ PASSED
✓ Integration Tests:     30+ / 30+ PASSED
✓ Load Test RPS:         50-200 req/sec
✓ Load Test Latency:     P95 < 200ms, P99 < 500ms
✓ Load Test Errors:      < 1% error rate
✓ Chaos Recovery:        > 99% recovery rate
✓ Monitoring:            All metrics flowing
```

### Example Grafana Metrics

```
Events Created/sec:      125 (↑)
Event Latency P99:       95ms (↓)
Reconstruction P95:      120ms (↓)
API Response P99:        450ms (→)
Active Entities:         1,250 (↑)
Event Log Size:          2.3 GB (↑)
Pending Queue:           0 (✓)
DB Pool Available:       85/100 (✓)
Error Rate:              0.5% (✓)
```

---

## 🔍 DETAILED TEST BREAKDOWN

### Unit Tests (50+ cases)

```python
TestStateReconstruction (5 tests)
  ✓ test_init_event                    <10ms
  ✓ test_update_event                  <10ms
  ✓ test_complex_state_transitions     <10ms
  ✓ test_reset_event                   <10ms
  ✓ test_large_event_log (1000 events) <50ms

TestEventValidation (2 tests)
  ✓ test_event_creation                <5ms
  ✓ test_event_timestamp               <5ms

TestIntegrationWorkflows (3 tests)
  ✓ test_user_creation_workflow        <100ms
  ✓ test_transaction_workflow          <100ms
  ✓ test_concurrent_updates (10 users) <200ms

TestChaosEngineering (2 tests)
  ✓ test_failure_recovery              <500ms
  ✓ test_high_latency_scenario         >1000ms (expected)

TestSnapshotStrategy (2 tests)
  ✓ test_snapshot_creation             <10ms
  ✓ test_snapshot_interval             <50ms

TestPerformanceBenchmarks (5+ tests)
  ✓ test_event_creation_performance    1000 iterations
  ✓ test_state_reconstruction_performance  1000 iterations
```

### Load Test Stages

```
Stage 1: Ramp (0 → 10 users, 30s)
  │ Requests: 50-100
  │ Latency: 10-20ms
  │ Errors: 0
  └─→ ✓ Pass

Stage 2: Ramp (10 → 50 users, 90s)
  │ Requests: 250-500
  │ Latency: 15-50ms
  │ Errors: 0-2
  └─→ ✓ Pass

Stage 3: Sustained (50 → 100 users, 120s)
  │ Requests: 500-1000
  │ Latency: 50-150ms
  │ Errors: 5-10
  │ Error Rate: <1%
  └─→ ✓ Pass

Stage 4: Spike (100 → 200 users, 30s)
  │ Requests: 1000-2000
  │ Latency: 100-300ms
  │ Errors: 10-20
  │ Error Rate: <1%
  └─→ ✓ Pass

Stage 5: Sustained (200 → 100 users, 120s)
  │ Requests: 500-1000
  │ Latency: 50-150ms
  │ Errors: 5-10
  └─→ ✓ Pass

Stage 6: Ramp Down (100 → 0 users, 30s)
  │ Requests: 50-100
  │ Latency: 10-20ms
  │ Errors: 0
  └─→ ✓ Pass
```

---

## 📊 METRICS COLLECTED

### Prometheus Metrics (25+)

```
Counter Metrics:
  ✓ phantom_events_created_total
  ✓ phantom_events_processed_total
  ✓ phantom_reconstruction_failures_total

Histogram Metrics (with percentiles):
  ✓ phantom_event_creation_duration_ms
  ✓ phantom_state_reconstruction_duration_ms
  ✓ phantom_api_request_duration_ms

Gauge Metrics (current state):
  ✓ phantom_active_entities
  ✓ phantom_event_log_size_bytes
  ✓ phantom_pending_events_queue
  ✓ phantom_db_connection_pool_available

Summary Metrics:
  ✓ phantom_snapshot_creation_duration_seconds
```

### Structured Logs (JSON format)

```json
{
  "timestamp": "2026-04-15T10:30:45.123Z",
  "level": "INFO",
  "service": "phantom-runtime",
  "message": "Event created successfully",
  "entity_id": "user_123",
  "duration_ms": 25.5,
  "trace_id": "trace_1234567890",
  "span_id": "span_001",
  "tags": {
    "service": "phantom-runtime",
    "environment": "test"
  }
}
```

### OpenTelemetry Traces

```
Trace ID: trace_1234567890
├─ Span: event_creation
│  ├─ start_time: 10:30:45.100
│  ├─ duration: 45ms
│  ├─ status: OK
│  └─ attributes:
│      ├─ entity_id: user_123
│      ├─ event_type: init
│      └─ payload_size: 256 bytes
│
├─ Span: state_reconstruction
│  ├─ start_time: 10:30:45.150
│  ├─ duration: 25ms
│  ├─ status: OK
│  └─ attributes:
│      ├─ event_count: 5
│      └─ state_size: 512 bytes
│
└─ Span: database_write
   ├─ start_time: 10:30:45.180
   ├─ duration: 15ms
   ├─ status: OK
   └─ attributes:
       ├─ rows_affected: 1
       └─ query_time: 5ms
```

---

## 🎯 POST-TEST ANALYSIS

### 1. Review Metrics

```bash
# Query Prometheus
curl http://localhost:9090/api/v1/query?query=phantom_events_created_total

# Expected: metric exists with values

# Check percentiles
curl http://localhost:9090/api/v1/query?query=histogram_quantile\(0.99,phantom_api_request_duration_ms\)

# Expected: <500ms P99
```

### 2. Review Logs

```bash
# Query Loki
curl -s 'http://localhost:3100/loki/api/v1/query_range?query={job="phantom-runtime"}&start=...&end=...' | jq .

# Filter errors
curl -s 'http://localhost:3100/loki/api/v1/query_range?query={job="phantom-runtime",level="ERROR"}' | jq .
```

### 3. Review Traces

```bash
# Access Jaeger UI
open http://localhost:16686

# Search for traces:
# - Service: phantom-runtime
# - Operation: event_creation
# - Tags: entity_id=user_123
# - Min Duration: 0ms
# - Max Duration: 100ms
```

### 4. Generate Report

```bash
# Extract metrics summary
python -c "
import requests
import json

response = requests.get('http://localhost:9090/api/v1/query', params={
    'query': 'phantom_api_request_duration_ms'
})

data = response.json()
print(json.dumps(data, indent=2))
"

# Expected: JSON with all metrics
```

---

## ✅ COMPLETION CHECKLIST

- [ ] All dependencies installed
- [ ] Monitoring stack running (docker ps shows 6+ containers)
- [ ] Unit tests: 80+ passed
- [ ] Integration tests: 30+ passed
- [ ] Load test: 6 stages completed
- [ ] Chaos tests: 5+ scenarios passed
- [ ] Prometheus metrics: 25+ metrics collected
- [ ] Grafana dashboard: All panels showing data
- [ ] Jaeger traces: Traces visible
- [ ] Structured logs: JSON format verified
- [ ] Alerts: 6+ alert rules defined
- [ ] Report: Generated and reviewed

---

## 🚨 TROUBLESHOOTING

### Tests Failing

```bash
# 1. Check Python version
python3 --version

# 2. Check imports
python -c "import pytest; import structlog; print('OK')"

# 3. Run with verbose output
pytest tests/test_suite.py -vv -s

# 4. Check logs
tail -f /tmp/phantom_test.log
```

### Load Test Failing

```bash
# 1. Check backend is running
curl http://localhost:8001/api/health

# 2. Check K6 version
k6 version

# 3. Run with debug
k6 run tests/load-tests-k6.js --vus 1 --iterations 1 -v

# 4. Check logs
k6 run tests/load-tests-k6.js 2>&1 | head -50
```

### Monitoring Not Working

```bash
# 1. Check services
docker-compose -f docker-compose.monitoring.yml ps

# 2. Check logs
docker logs phantom_prometheus | tail -20

# 3. Restart services
docker-compose -f docker-compose.monitoring.yml restart

# 4. Check ports
lsof -i :9090,3000,9093
```

---

## 📞 SUPPORT

**Questions?**
- Check test outputs for error messages
- Review logs in /var/log/phantom/
- Check Prometheus targets at http://localhost:9090/targets
- View Grafana datasource config at http://localhost:3000/datasources

---

**Status:** ✅ **READY TO EXECUTE**

**Run Everything:**
```bash
./run-all-tests.sh  # Execute complete test suite
```

