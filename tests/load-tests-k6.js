"""
K6 Load Testing Scenarios - JavaScript
Tests sustained load, burst traffic, database stress
"""

// k6 run tests/load-tests-k6.js

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

export default function () {
  const baseUrl = 'http://localhost:8001';
  let workspaceId = 'ws_' + __VU + '_' + __ITER;
  
  group('Event Creation Load Test', function () {
    // Create workspace
    let wsRes = http.post(`${baseUrl}/api/workspaces`, JSON.stringify({
      name: 'LoadTest_' + __ITER,
      description: 'Load test workspace'
    }), {
      headers: { 'Content-Type': 'application/json' }
    });
    
    check(wsRes, {
      'workspace created': (r) => r.status === 201 || r.status === 200,
    });
    
    // Create multiple events
    for (let i = 0; i < 5; i++) {
      let startTime = new Date();
      
      let eventRes = http.post(`${baseUrl}/api/events`, JSON.stringify({
        entity_id: `entity_${__VU}_${i}`,
        event_type: i === 0 ? 'init' : 'update',
        payload: {
          index: i,
          timestamp: new Date().toISOString(),
          value: Math.random() * 1000,
          batch: __ITER
        }
      }), {
        headers: { 'Content-Type': 'application/json' }
      });
      
      let duration = new Date() - startTime;
      eventCreationTime.add(duration);
      requestCount.add(1);
      
      check(eventRes, {
        'event created': (r) => r.status === 201 || r.status === 200,
        'event response time < 500ms': (r) => r.timings.duration < 500,
      });
      
      if (eventRes.status !== 200 && eventRes.status !== 201) {
        apiErrorRate.add(1);
      }
      
      sleep(0.1);
    }
  });
  
  group('State Reconstruction Load Test', function () {
    let startTime = new Date();
    
    let stateRes = http.get(`${baseUrl}/api/state/entity_${__VU}_0`);
    
    let duration = new Date() - startTime;
    stateReconstructionTime.add(duration);
    requestCount.add(1);
    
    check(stateRes, {
      'state retrieved': (r) => r.status === 200,
      'reconstruction time < 200ms': (r) => r.timings.duration < 200,
      'has state data': (r) => r.body.includes('state'),
    });
    
    if (stateRes.status !== 200) {
      apiErrorRate.add(1);
    }
  });
  
  group('High Concurrency Scenario', function () {
    // Simulate concurrent requests
    let responses = http.batch([
      ['GET', `${baseUrl}/api/state/entity_${__VU}_0`],
      ['GET', `${baseUrl}/api/state/entity_${__VU}_1`],
      ['GET', `${baseUrl}/api/state/entity_${__VU}_2`],
      ['POST', `${baseUrl}/api/events`, JSON.stringify({
        entity_id: `entity_${__VU}_concurrent`,
        event_type: 'update',
        payload: { concurrent: true, vu: __VU }
      })],
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
  console.log('K6 Load Test Summary:');
  console.log('=====================');
  console.log('Requests: ' + data.metrics.requests_total.value);
  console.log('Event Creation - P95: ' + data.metrics.event_creation_time.values['p(95)']);
  console.log('Reconstruction - P95: ' + data.metrics.state_reconstruction_time.values['p(95)']);
  console.log('Error Rate: ' + (data.metrics.api_errors.value * 100).toFixed(2) + '%');
  
  return {
    'stdout': data.summary,
    'json': JSON.stringify(data, null, 2),
  };
}
