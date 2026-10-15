/*
 * K6 Load Testing Scenarios
 * Tests sustained load, burst traffic, database stress.
 *
 * Needs a running backend and the one-time bootstrap key (PHANTOM_BOOTSTRAP_ADMIN_KEY):
 *   k6 run -e BASE_URL=http://localhost:8001 -e BOOTSTRAP_KEY=<key> tests/load-tests-k6.js
 * setup() creates one workspace with the bootstrap key; every VU then writes with that
 * workspace's API key. Writes need X-API-Key and workspace creation is closed to anonymous callers.
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Counter, Trend, Gauge, Rate } from 'k6/metrics';

// Custom metrics
let eventCreationTime = new Trend('event_creation_time');
let stateReconstructionTime = new Trend('state_reconstruction_time');
let apiErrorRate = new Rate('api_errors');
let activeConnections = new Gauge('active_connections');
let requestCount = new Counter('requests_total');

// Test configuration
export let options = {
  stages: [
    { duration: '30s', target: 10 },    // Ramp up to 10 users
    { duration: '1m30s', target: 50 },  // Ramp up to 50 users
    { duration: '2m', target: 100 },    // Ramp up to 100 users (sustained load)
    { duration: '30s', target: 200 },   // Spike to 200 users (burst)
    { duration: '2m', target: 100 },    // Back to 100 users
    { duration: '30s', target: 0 },     // Ramp down
  ],
  thresholds: {
    'event_creation_time': ['p(95)<200', 'p(99)<500'],
    'state_reconstruction_time': ['p(95)<200', 'p(99)<500'],
    'api_errors': ['rate<0.1'],  // Error rate < 10%
    'http_req_duration': ['p(95)<500', 'p(99)<1000'],
  },
};

const baseUrl = __ENV.BASE_URL || 'http://localhost:8001';

export function setup() {
  if (!__ENV.BOOTSTRAP_KEY) {
    throw new Error('set -e BOOTSTRAP_KEY=<PHANTOM_BOOTSTRAP_ADMIN_KEY>');
  }
  const res = http.post(`${baseUrl}/api/workspaces/`, JSON.stringify({ name: 'LoadTest_' + Date.now() }), {
    headers: { 'Content-Type': 'application/json', 'X-Bootstrap-Key': __ENV.BOOTSTRAP_KEY },
  });
  if (res.status !== 201) {
    throw new Error('workspace creation failed: ' + res.status + ' ' + res.body);
  }
  return { apiKey: res.json('api_key') };
}

export default function (data) {
  const params = { headers: { 'Content-Type': 'application/json', 'X-API-Key': data.apiKey } };

  group('Event Creation Load Test', function () {
    // Create multiple events
    for (let i = 0; i < 5; i++) {
      let startTime = new Date();
      
      let eventRes = http.post(`${baseUrl}/api/events/`, JSON.stringify({
        entity_id: `entity_${__VU}_${i}`,
        event_type: i === 0 ? 'init' : 'update',
        payload: {
          index: i,
          timestamp: new Date().toISOString(),
          value: Math.random() * 1000,
          batch: __ITER
        }
      }), params);
      
      let duration = new Date() - startTime;
      eventCreationTime.add(duration);
      requestCount.add(1);
      
      check(eventRes, {
        'event created': (r) => r.status === 201 || r.status === 200,
        'event response time < 500ms': (r) => r.timings.duration < 500,
      });
      
      apiErrorRate.add(eventRes.status !== 200 && eventRes.status !== 201);
      
      sleep(0.1);
    }
  });
  
  group('State Reconstruction Load Test', function () {
    let startTime = new Date();
    
    let stateRes = http.get(`${baseUrl}/api/state/entity_${__VU}_0`, params);
    
    let duration = new Date() - startTime;
    stateReconstructionTime.add(duration);
    requestCount.add(1);
    
    check(stateRes, {
      'state retrieved': (r) => r.status === 200,
      'reconstruction time < 200ms': (r) => r.timings.duration < 200,
      'has state data': (r) => r.body.includes('state'),
    });
    
    apiErrorRate.add(stateRes.status !== 200);
  });
  
  group('High Concurrency Scenario', function () {
    // Simulate concurrent requests
    let responses = http.batch([
      ['GET', `${baseUrl}/api/state/entity_${__VU}_0`, null, params],
      ['GET', `${baseUrl}/api/state/entity_${__VU}_1`, null, params],
      ['GET', `${baseUrl}/api/state/entity_${__VU}_2`, null, params],
      ['POST', `${baseUrl}/api/events/`, JSON.stringify({
        entity_id: `entity_${__VU}_concurrent`,
        event_type: 'update',
        payload: { concurrent: true, vu: __VU }
      }), params],
    ]);
    
    let successCount = responses.filter(r => r.status === 200 || r.status === 201).length;
    check(successCount, {
      'batch success rate >= 75%': (count) => count >= 3,
    });
    
    requestCount.add(responses.length);
  });
  
  sleep(Math.random() * 2);
}

export function handleSummary(data) {
  const m = data.metrics;
  const text = [
    'K6 Load Test Summary',
    '====================',
    'Requests: ' + m.http_reqs.values.count,
    'Event Creation - P95: ' + m.event_creation_time.values['p(95)'] + ' ms',
    'Reconstruction - P95: ' + m.state_reconstruction_time.values['p(95)'] + ' ms',
    'HTTP P95 / P99: ' + m.http_req_duration.values['p(95)'] + ' / ' + m.http_req_duration.values['p(99)'] + ' ms',
    'Error Rate: ' + (m.api_errors.values.rate * 100).toFixed(2) + '%',
    '',
  ].join('\n');
  return {
    stdout: text,
    'k6-summary.json': JSON.stringify(data, null, 2),
  };
}
