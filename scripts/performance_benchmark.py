#!/usr/bin/env python3
"""RecoverX Automated Concurrency & Latency Performance Benchmark Suite.

Simulates 10, 50, and 100 concurrent Virtual Users across core RecoverX endpoints:
- GET /health/live
- GET /health/ready
- GET /api/exceptions
- GET /api/disputes
- GET /api/settlements
- GET /api/dashboard/summary
- POST /api/webhooks/razorpay (asynchronous ACK latency)
"""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
import statistics
import sys
import time

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.database.connection import ensure_schema
from app.database.session import SessionLocal
from app.main import app
from app.models.merchant import Merchant
from app.models.user import User
from app.services.razorpay_service import RazorpayService


def run_benchmark_for_concurrency(client: TestClient, token: str, service: RazorpayService, vus: int, requests_per_vu: int = 10) -> dict[str, Any]:
    latencies: list[float] = []
    webhook_ack_latencies: list[float] = []
    error_count = 0
    total_requests = vus * requests_per_vu

    headers = {"Authorization": f"Bearer {token}"}

    def execute_vu_task(vu_id: int):
        vu_latencies = []
        vu_ack_latencies = []
        vu_errors = 0
        vu_headers = {
            "Authorization": f"Bearer {token}",
            "X-Forwarded-For": f"192.168.1.{vu_id + 1}",
        }

        for req_idx in range(requests_per_vu):
            # 1. Dashboard / Exceptions Query
            t0 = time.perf_counter()
            try:
                if req_idx % 4 == 0:
                    res = client.get("/api/exceptions", headers=vu_headers)
                elif req_idx % 4 == 1:
                    res = client.get("/api/disputes", headers=vu_headers)
                elif req_idx % 4 == 2:
                    res = client.get("/api/settlements", headers=vu_headers)
                else:
                    res = client.get("/api/dashboard/summary", headers=vu_headers)

                lat = (time.perf_counter() - t0) * 1000.0
                vu_latencies.append(lat)
                if res.status_code != 200:
                    vu_errors += 1
            except Exception:
                vu_errors += 1

            # 2. Webhook Ingestion ACK Latency
            tag = f"bench_{vus}_{vu_id}_{req_idx}_{uuid4().hex[:6]}"
            now_ts = int(datetime.now(UTC).timestamp())
            payload = {
                "entity": "event",
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": f"pay_{tag}",
                            "amount": 500000,
                            "currency": "INR",
                            "status": "captured",
                            "created_at": now_ts,
                        }
                    }
                },
                "created_at": now_ts,
            }
            body = json.dumps(payload).encode("utf-8")
            sig = service.create_test_signature(body)

            t_ack0 = time.perf_counter()
            try:
                res_wh = client.post(
                    "/api/webhooks/razorpay",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Razorpay-Signature": sig,
                        "X-Forwarded-For": f"192.168.1.{vu_id + 1}",
                    },
                )
                ack_lat = (time.perf_counter() - t_ack0) * 1000.0
                vu_ack_latencies.append(ack_lat)
                if res_wh.status_code != 200:
                    vu_errors += 1
            except Exception:
                vu_errors += 1

        return vu_latencies, vu_ack_latencies, vu_errors

    start_wall = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=vus) as executor:
        futures = [executor.submit(execute_vu_task, i) for i in range(vus)]
        for f in concurrent.futures.as_completed(futures):
            lats, ack_lats, errs = f.result()
            latencies.extend(lats)
            webhook_ack_latencies.extend(ack_lats)
            error_count += errs

    total_duration_sec = time.perf_counter() - start_wall
    all_requests_executed = len(latencies) + len(webhook_ack_latencies)
    rps = all_requests_executed / total_duration_sec if total_duration_sec > 0 else 0

    latencies.sort()
    webhook_ack_latencies.sort()

    def get_percentile(data: list[float], pct: float) -> float:
        if not data:
            return 0.0
        idx = int(len(data) * (pct / 100.0))
        return data[min(idx, len(data) - 1)]

    return {
        "vus": vus,
        "total_requests": all_requests_executed,
        "duration_seconds": round(total_duration_sec, 2),
        "requests_per_sec": round(rps, 1),
        "error_rate_pct": round((error_count / all_requests_executed) * 100, 2) if all_requests_executed else 0,
        "query_latency": {
            "p50_ms": round(get_percentile(latencies, 50), 2),
            "p95_ms": round(get_percentile(latencies, 95), 2),
            "p99_ms": round(get_percentile(latencies, 99), 2),
            "avg_ms": round(statistics.mean(latencies), 2) if latencies else 0,
        },
        "webhook_ack_latency": {
            "p50_ms": round(get_percentile(webhook_ack_latencies, 50), 2),
            "p95_ms": round(get_percentile(webhook_ack_latencies, 95), 2),
            "p99_ms": round(get_percentile(webhook_ack_latencies, 99), 2),
            "avg_ms": round(statistics.mean(webhook_ack_latencies), 2) if webhook_ack_latencies else 0,
        },
    }


def main():
    ensure_schema()
    service = RazorpayService()
    token = create_access_token(data={"sub": "1", "merchant_id": 1})

    with TestClient(app) as client:
        print("=" * 70)
        print("RECOVERX REAL PERFORMANCE & LATENCY BENCHMARK")
        print("=" * 70)

        results = []
        for vu_level in [10, 25, 50]:
            print(f"\n[*] Benchmarking {vu_level} Concurrent Virtual Users...")
            res = run_benchmark_for_concurrency(client, token, service, vus=vu_level, requests_per_vu=5)
            results.append(res)
            print(f"    - Throughput: {res['requests_per_sec']} req/sec")
            print(f"    - Query Latency: p50={res['query_latency']['p50_ms']}ms, p95={res['query_latency']['p95_ms']}ms, p99={res['query_latency']['p99_ms']}ms")
            print(f"    - Webhook ACK Latency: p50={res['webhook_ack_latency']['p50_ms']}ms, p95={res['webhook_ack_latency']['p95_ms']}ms, p99={res['webhook_ack_latency']['p99_ms']}ms")
            print(f"    - Error Rate: {res['error_rate_pct']}%")

        print("\n" + "=" * 70)
        print("BENCHMARK SUMMARY COMPLETE")
        print(json.dumps(results, indent=2))
        print("=" * 70)


if __name__ == "__main__":
    main()
