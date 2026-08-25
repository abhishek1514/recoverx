#!/usr/bin/env python3
"""RecoverX Health Check CLI Utility.

Probes /health/live and /health/ready endpoints against a local or remote target URL.
"""

from __future__ import annotations

import argparse
import sys
import httpx


def check_health(target_url: str, timeout: float = 10.0) -> bool:
    base_url = target_url.rstrip("/")
    live_url = f"{base_url}/health/live"
    ready_url = f"{base_url}/health/ready"

    print(f"[*] Checking RecoverX health at: {base_url}")
    all_ok = True

    # 1. Liveness check
    try:
        resp = httpx.get(live_url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[PASS] Liveness probe OK (HTTP 200): service='{data.get('service')}', env='{data.get('environment')}'")
        else:
            print(f"[FAIL] Liveness probe FAILED (HTTP {resp.status_code}): {resp.text}")
            all_ok = False
    except Exception as exc:
        print(f"[FAIL] Liveness probe connection error: {exc}")
        all_ok = False

    # 2. Readiness check
    try:
        resp = httpx.get(ready_url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[PASS] Readiness probe OK (HTTP 200): database='{data.get('database')}', queue='{data.get('durable_queue')}'")
        else:
            print(f"[FAIL] Readiness probe FAILED (HTTP {resp.status_code}): {resp.text}")
            all_ok = False
    except Exception as exc:
        print(f"[FAIL] Readiness probe connection error: {exc}")
        all_ok = False

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(description="RecoverX Health Check Utility")
    parser.add_argument("--url", default="http://localhost:8000", help="Target API base URL (default: http://localhost:8000)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds (default: 10.0)")
    args = parser.parse_args()

    success = check_health(args.url, args.timeout)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

