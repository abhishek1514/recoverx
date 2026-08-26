#!/usr/bin/env python3
"""RecoverX Phase 7A - Performance Bottleneck & Latency Diagnostic Suite.

Instruments and measures:
1. Server-side webhook ACK timing vs client round-trip
2. Database query counts and query durations per endpoint
3. SQLite lock contention and connection acquisition latency
4. Concurrency degradation curve across 1, 5, 10, 25, 50 VUs
5. Worker processing latency in isolation vs Webhook ACK in isolation
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import statistics
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.core.security import create_access_token
from app.database.connection import ensure_schema, engine
from app.database.session import SessionLocal
from app.main import app
from app.models.merchant import Merchant
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.services.razorpay_service import RazorpayService
from app.workers.tasks import process_razorpay_webhook


# =============================================================================
# 1. SQL Query Profiler & Listener
# =============================================================================
class QueryProfiler:
    def __init__(self):
        self.queries: list[dict[str, Any]] = []
        self.active = False

    def start(self):
        self.queries.clear()
        self.active = True

    def stop(self):
        self.active = False

    def log_query(self, statement: str, duration_ms: float):
        if self.active:
            self.queries.append({
                "statement": statement.strip().replace("\n", " ")[:120],
                "duration_ms": round(duration_ms, 3),
            })


profiler = QueryProfiler()


@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.perf_counter()


@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = (time.perf_counter() - context._query_start_time) * 1000.0
    profiler.log_query(statement, total)


# =============================================================================
# 2. Endpoint Query Count & Latency Breakdown
# =============================================================================
def profile_endpoint(client: TestClient, method: str, url: str, headers: dict[str, str], payload: Any = None) -> dict[str, Any]:
    profiler.start()
    t0 = time.perf_counter()
    if method == "GET":
        res = client.get(url, headers=headers)
    elif method == "POST":
        res = client.post(url, json=payload, headers=headers)
    total_time_ms = (time.perf_counter() - t0) * 1000.0
    profiler.stop()

    query_durations = [q["duration_ms"] for q in profiler.queries]
    total_db_time_ms = sum(query_durations)
    slowest = max(query_durations) if query_durations else 0.0

    return {
        "endpoint": f"{method} {url}",
        "status_code": res.status_code,
        "total_time_ms": round(total_time_ms, 2),
        "db_query_count": len(profiler.queries),
        "total_db_time_ms": round(total_db_time_ms, 2),
        "slowest_query_ms": round(slowest, 2),
        "queries": list(profiler.queries),
    }


# =============================================================================
# 3. Server-Side Webhook Breakdown
# =============================================================================
def benchmark_server_webhook_breakdown(service: RazorpayService, runs: int = 100) -> dict[str, Any]:
    sig_times = []
    lookup_times = []
    persist_times = []
    total_server_ack_times = []

    for i in range(runs):
        now_ts = int(datetime.now(UTC).timestamp())
        payload = {
            "entity": "event",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_diag_{i}_{uuid4().hex[:6]}",
                        "amount": 250000,
                        "currency": "INR",
                        "status": "captured",
                        "created_at": now_ts,
                    }
                }
            },
            "created_at": now_ts,
        }
        body = json.dumps(payload).encode("utf-8")

        # Step 1: Signature Verification
        t_sig0 = time.perf_counter()
        sig = service.create_test_signature(body)
        is_valid = service.verify_webhook_signature(body, sig)
        sig_dur = (time.perf_counter() - t_sig0) * 1000.0
        sig_times.append(sig_dur)

        # Step 2: Event Lookup
        event_id = f"evt_diag_{i}_{uuid4().hex[:6]}"
        t_look0 = time.perf_counter()
        with SessionLocal() as db:
            existing = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
            look_dur = (time.perf_counter() - t_look0) * 1000.0
            lookup_times.append(look_dur)

            # Step 3: Event Persistence
            t_per0 = time.perf_counter()
            wb = WebhookEvent(
                event_id=event_id,
                event_type="payment.captured",
                payload=json.dumps(payload),
                status="received",
            )
            db.add(wb)
            db.commit()
            per_dur = (time.perf_counter() - t_per0) * 1000.0
            persist_times.append(per_dur)

        total_server_ack_times.append(sig_dur + look_dur + per_dur)

    return {
        "signature_verification_ms": {
            "p50": round(statistics.median(sig_times), 3),
            "p95": round(statistics.quantiles(sig_times, n=20)[18], 3),
            "avg": round(statistics.mean(sig_times), 3),
        },
        "event_lookup_ms": {
            "p50": round(statistics.median(lookup_times), 3),
            "p95": round(statistics.quantiles(lookup_times, n=20)[18], 3),
            "avg": round(statistics.mean(lookup_times), 3),
        },
        "event_persistence_ms": {
            "p50": round(statistics.median(persist_times), 3),
            "p95": round(statistics.quantiles(persist_times, n=20)[18], 3),
            "avg": round(statistics.mean(persist_times), 3),
        },
        "total_server_ack_ms": {
            "p50": round(statistics.median(total_server_ack_times), 3),
            "p95": round(statistics.quantiles(total_server_ack_times, n=20)[18], 3),
            "avg": round(statistics.mean(total_server_ack_times), 3),
        },
    }


# =============================================================================
# 4. Worker Processing Latency in Isolation
# =============================================================================
def benchmark_worker_processing_latency(service: RazorpayService, runs: int = 50) -> dict[str, Any]:
    worker_times = []
    for i in range(runs):
        now_ts = int(datetime.now(UTC).timestamp())
        event_id = f"evt_worker_bench_{i}_{uuid4().hex[:6]}"
        payload = {
            "entity": "event",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_worker_{i}_{uuid4().hex[:6]}",
                        "amount": 58000000,
                        "currency": "INR",
                        "status": "captured",
                        "created_at": now_ts,
                    }
                }
            },
            "created_at": now_ts,
        }

        with SessionLocal() as db:
            wb = WebhookEvent(
                event_id=event_id,
                event_type="payment.captured",
                payload=json.dumps(payload),
                status="received",
            )
            db.add(wb)
            db.commit()

        # Measure standalone worker task execution
        t0 = time.perf_counter()
        process_razorpay_webhook(event_id)
        dur_ms = (time.perf_counter() - t0) * 1000.0
        worker_times.append(dur_ms)

    return {
        "runs": runs,
        "worker_processing_latency_ms": {
            "p50": round(statistics.median(worker_times), 2),
            "p95": round(statistics.quantiles(worker_times, n=20)[18], 2),
            "p99": round(max(worker_times), 2),
            "avg": round(statistics.mean(worker_times), 2),
        },
    }


# =============================================================================
# 5. Concurrency Saturation Curve (1, 5, 10, 25, 50 VUs)
# =============================================================================
def run_concurrency_curve(client: TestClient, token: str, service: RazorpayService, vu_list: list[int] = [1, 5, 10, 25, 50]) -> list[dict[str, Any]]:
    results = []

    for vus in vu_list:
        latencies = []
        errors = 0
        reqs_per_vu = 5
        total_expected = vus * reqs_per_vu

        def vu_task(vu_id: int):
            vu_lats = []
            vu_errs = 0
            headers = {
                "Authorization": f"Bearer {token}",
                "X-Forwarded-For": f"10.0.0.{vu_id + 1}",
            }
            for i in range(reqs_per_vu):
                t0 = time.perf_counter()
                try:
                    if i % 2 == 0:
                        res = client.get("/api/exceptions", headers=headers)
                    else:
                        res = client.get("/api/dashboard/summary", headers=headers)
                    lat = (time.perf_counter() - t0) * 1000.0
                    vu_lats.append(lat)
                    if res.status_code != 200:
                        vu_errs += 1
                except Exception:
                    vu_errs += 1
            return vu_lats, vu_errs

        t_start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=vus) as executor:
            futures = [executor.submit(vu_task, i) for i in range(vus)]
            for f in concurrent.futures.as_completed(futures):
                lats, errs = f.result()
                latencies.extend(lats)
                errors += errs
        t_dur = time.perf_counter() - t_start

        latencies.sort()
        rps = len(latencies) / t_dur if t_dur > 0 else 0

        p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
        p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0

        results.append({
            "vus": vus,
            "requests": len(latencies),
            "duration_sec": round(t_dur, 2),
            "throughput_rps": round(rps, 1),
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "error_rate_pct": round((errors / total_expected) * 100, 2) if total_expected else 0,
        })

    return results


def main():
    ensure_schema()
    service = RazorpayService()
    token = create_access_token(data={"sub": "1", "merchant_id": 1})
    headers = {"Authorization": f"Bearer {token}", "X-Forwarded-For": "127.0.0.1"}

    with TestClient(app) as client:
        print("=" * 75)
        print("RECOVERX PHASE 7A - PERFORMANCE BOTTLENECK & LATENCY INVESTIGATION")
        print("=" * 75)

        # 1. Database & SQL Query Profiling
        print("\n--- [1] SQL Query Profiling per Endpoint ---")
        endpoints_to_profile = [
            ("GET", "/health/live", None),
            ("GET", "/health/ready", None),
            ("GET", "/api/exceptions", None),
            ("GET", "/api/exceptions/metrics", None),
            ("GET", "/api/disputes", None),
            ("GET", "/api/settlements", None),
            ("GET", "/api/dashboard/summary", None),
        ]
        endpoint_profiles = []
        for method, path, body in endpoints_to_profile:
            p = profile_endpoint(client, method, path, headers, body)
            endpoint_profiles.append(p)
            print(f"  {p['endpoint']:<35} | Total: {p['total_time_ms']:>6.2f}ms | Queries: {p['db_query_count']:>2} | DB Time: {p['total_db_time_ms']:>6.2f}ms | Slowest: {p['slowest_query_ms']:>6.2f}ms")

        # 2. Webhook Server-Side Timing Breakdown
        print("\n--- [2] Server-Side Webhook ACK Timing (Isolated Server Time) ---")
        server_ack = benchmark_server_webhook_breakdown(service, runs=100)
        print(f"  Signature Verification : p50 = {server_ack['signature_verification_ms']['p50']}ms, p95 = {server_ack['signature_verification_ms']['p95']}ms")
        print(f"  Event DB Lookup        : p50 = {server_ack['event_lookup_ms']['p50']}ms, p95 = {server_ack['event_lookup_ms']['p95']}ms")
        print(f"  Event DB Persistence   : p50 = {server_ack['event_persistence_ms']['p50']}ms, p95 = {server_ack['event_persistence_ms']['p95']}ms")
        print(f"  TOTAL SERVER-SIDE ACK  : p50 = {server_ack['total_server_ack_ms']['p50']}ms, p95 = {server_ack['total_server_ack_ms']['p95']}ms")

        # 3. Worker Processing Latency Breakdown
        print("\n--- [3] Standalone Background Worker Processing Latency ---")
        worker_res = benchmark_worker_processing_latency(service, runs=30)
        print(f"  Worker Execution Time  : p50 = {worker_res['worker_processing_latency_ms']['p50']}ms, p95 = {worker_res['worker_processing_latency_ms']['p95']}ms, p99 = {worker_res['worker_processing_latency_ms']['p99']}ms")

        # 4. Concurrency Saturation Curve
        print("\n--- [4] Concurrency Saturation Curve (1 to 50 VUs) ---")
        curve = run_concurrency_curve(client, token, service, [1, 5, 10, 25, 50])
        print(f"  {'VUs':<5} | {'Throughput (rps)':<18} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | {'p99 (ms)':<10} | {'Errors':<8}")
        print("  " + "-" * 70)
        for c in curve:
            print(f"  {c['vus']:<5} | {c['throughput_rps']:<18} | {c['p50_ms']:<10} | {c['p95_ms']:<10} | {c['p99_ms']:<10} | {c['error_rate_pct']}%")

        print("\n" + "=" * 75)
        print("DIAGNOSTIC SUMMARY COMPLETE")
        diagnostic_payload = {
            "endpoint_profiles": endpoint_profiles,
            "server_webhook_ack": server_ack,
            "worker_processing": worker_res,
            "concurrency_curve": curve,
        }
        print(json.dumps(diagnostic_payload, indent=2))
        print("=" * 75)


if __name__ == "__main__":
    main()

