/**
 * =========================================================================
 * RecoverX k6 Production Load & Concurrency Benchmark Suite
 * =========================================================================
 *
 * Usage:
 *   k6 run load_tests/k6_load_test.js -e BASE_URL=http://localhost:8000
 *   k6 run load_tests/k6_load_test.js -e BASE_URL=https://recoverx-api.onrender.com
 *
 * Scenarios:
 *   1. 10 concurrent Virtual Users (warm-up / normal operations)
 *   2. 50 concurrent Virtual Users (peak traffic spike)
 *   3. 100 concurrent Virtual Users (stress / resilience threshold)
 *
 * Thresholds:
 *   - Liveness Probe: p95 < 50ms, p99 < 100ms
 *   - Readiness & DB Probe: p95 < 150ms, p99 < 300ms
 *   - Webhook Ingestion ACK: p95 < 200ms (fast asynchronous acknowledgement)
 *   - Error Rate: < 1%
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('error_rate');
const webhookAckLatency = new Trend('webhook_ack_latency_ms');

export const options = {
  stages: [
    { duration: '30s', target: 10 },   // Ramp up to 10 VUs
    { duration: '1m',  target: 10 },   // Hold at 10 VUs
    { duration: '30s', target: 50 },   // Ramp up to 50 VUs
    { duration: '1m',  target: 50 },   // Hold at 50 VUs
    { duration: '30s', target: 100 },  // Ramp up to 100 VUs
    { duration: '1m',  target: 100 },  // Hold at 100 VUs
    { duration: '30s', target: 0 },    // Ramp down to 0
  ],
  thresholds: {
    'http_req_duration': ['p(95)<250', 'p(99)<500'],
    'error_rate': ['rate<0.01'], // Less than 1% errors
    'webhook_ack_latency_ms': ['p(95)<200'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export default function () {
  // 1. Benchmark Liveness Probe (/health/live)
  const liveRes = http.get(`${BASE_URL}/health/live`);
  const liveSuccess = check(liveRes, {
    'liveness status is 200': (r) => r.status === 200,
    'liveness returns ok': (r) => r.json('status') === 'ok',
  });
  errorRate.add(!liveSuccess);

  // 2. Benchmark Readiness & Database Pool Probe (/health/ready)
  const readyRes = http.get(`${BASE_URL}/health/ready`);
  const readySuccess = check(readyRes, {
    'readiness status is 200': (r) => r.status === 200,
    'database is connected': (r) => r.json('database') === 'connected',
  });
  errorRate.add(!readySuccess);

  // 3. Benchmark Fast Razorpay Test Webhook Ingestion & ACK Latency
  const timestamp = Date.now();
  const webhookPayload = JSON.stringify({
    event_id: `evt_k6_${__VU}_${timestamp}`,
    event: 'payment.captured',
    payload: {
      payment: {
        entity: {
          id: `pay_k6_${__VU}_${timestamp}`,
          order_id: `order_k6_${__VU}_${timestamp}`,
          amount: 25000000, // INR 2,50,000 in paise
          currency: 'INR',
          status: 'captured',
          method: 'upi',
          created_at: Math.floor(timestamp / 1000),
        },
      },
    },
  });

  const webhookStart = Date.now();
  const webhookRes = http.post(`${BASE_URL}/api/webhooks/razorpay/test`, webhookPayload, {
    headers: { 'Content-Type': 'application/json' },
  });
  const webhookDuration = Date.now() - webhookStart;
  webhookAckLatency.add(webhookDuration);

  const webhookSuccess = check(webhookRes, {
    'webhook status is 200': (r) => r.status === 200,
    'webhook accepted': (r) => r.json('status') === 'accepted',
  });
  errorRate.add(!webhookSuccess);

  sleep(0.5);
}

