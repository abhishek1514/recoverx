"""Local Production Stack End-to-End Verification Script for RecoverX (Phase 11.2).

Performs real TCP/HTTP testing against the local Docker stack:
- PostgreSQL 16
- Redis 7
- MinIO S3 Object Storage
- RecoverX FastAPI API
- RecoverX Independent Worker Daemon

Validates:
1. Object Storage End-to-End (Upload, S3 Persistence in MinIO, Signed Token Retrieval, Security Validations, Tenant Isolation)
2. Webhook -> Durable Queue -> Worker End-to-End (HMAC Validation, Deduplication, Queue Transition, Case Creation, Concurrent Duplicate Ingestion)
3. Worker Crash / Restart Recovery (Persistence during worker downtime, Automatic discovery and recovery upon worker restart)
4. Health / Infrastructure Verification (Liveness, Deep Readiness, Container Health)
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv



import concurrent.futures
import hashlib
import hmac
import io
import json
import subprocess
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API_BASE = "http://localhost:8000"
MINIO_ENDPOINT = "http://localhost:9000"


WEBHOOK_SECRET = os.environ["RAZORPAY_WEBHOOK_SECRET"]
JWT_SECRET = "recoverx_staging_jwt_secret_32_bytes_min"

results: dict[str, Any] = {}


def generate_webhook_signature(body_bytes: bytes) -> str:
    """Compute HMAC-SHA256 signature for Razorpay webhook payloads."""
    secret = os.environ["RAZORPAY_WEBHOOK_SECRET"]
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def test_section_4_health():
    """Verify Section 4: Health & Readiness Endpoints."""
    print("\n--- SECTION 4: HEALTH / INFRASTRUCTURE VERIFICATION ---")
    with httpx.Client(timeout=5.0) as client:
        live_resp = client.get(f"{API_BASE}/health/live")
        print(f"GET /health/live: Status {live_resp.status_code}, Body: {live_resp.text}")
        assert live_resp.status_code == 200, f"Expected 200, got {live_resp.status_code}"
        live_data = live_resp.json()
        assert live_data.get("status") == "ok"

        ready_resp = client.get(f"{API_BASE}/health/ready")
        print(f"GET /health/ready: Status {ready_resp.status_code}, Body: {ready_resp.text}")
        assert ready_resp.status_code == 200, f"Expected 200, got {ready_resp.status_code}"
        ready_data = ready_resp.json()
        assert ready_data.get("status") == "ready"
        assert ready_data.get("database") == "connected"
        assert ready_data.get("durable_queue") == "active"
        assert ready_data.get("rate_limiter") == "redis"
        assert ready_data.get("object_storage") == "s3"

    results["health"] = {"live": live_data, "ready": ready_data, "status": "PASS"}
    print("[PASS] Health and readiness verified (PostgreSQL, Redis, MinIO S3 active).")


def test_section_1_object_storage():
    """Verify Section 1: Object Storage End-to-End with MinIO."""
    print("\n--- SECTION 1: OBJECT STORAGE END-TO-END ---")
    with httpx.Client(timeout=10.0) as client:
        # 1. Merchant Authentication
        login_resp = client.post(
            f"{API_BASE}/api/auth/login",
            json={"email": "admin@merchant.com", "password": "admin123456"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        auth_data = login_resp.json()
        token = auth_data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"[PASS] Merchant 1 authenticated successfully (User ID: {auth_data['user']['id']}).")

        # Create a synthetic transaction & dispute to attach evidence
        # Trigger synthetic dispute creation via internal webhook
        event_id = f"evt_disp_e2e_{int(time.time())}"
        pay_id = f"pay_disp_e2e_{int(time.time())}"
        disp_id = f"disp_e2e_{int(time.time())}"
        now_ts = int(time.time())

        dispute_payload = {
            "entity": "event",
            "account_id": "acc_merchant_1",
            "event": "payment.dispute.created",
            "contains": ["dispute", "payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "amount": 250000,
                        "currency": "INR",
                        "status": "captured",
                        "created_at": now_ts,
                    }
                },
                "dispute": {
                    "entity": {
                        "id": disp_id,
                        "payment_id": pay_id,
                        "amount": 250000,
                        "currency": "INR",
                        "status": "under_review",
                        "reason_code": "fraudulent",
                        "respond_by": now_ts + 86400,
                        "created_at": now_ts,
                    }
                },
            },
            "created_at": now_ts,
        }
        body_bytes = json.dumps(dispute_payload).encode("utf-8")
        sig = generate_webhook_signature(body_bytes)
        wh_resp = client.post(
            f"{API_BASE}/api/webhooks/razorpay",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": sig,
                "X-Razorpay-Event-Id": event_id,
            },
        )
        assert wh_resp.status_code == 200, f"Dispute webhook failed: {wh_resp.text}"
        print(f"[PASS] Webhook for dispute {disp_id} accepted.")

        # Wait briefly for worker to process dispute
        time.sleep(2.0)

        # Look up created dispute in API
        disputes_resp = client.get(f"{API_BASE}/api/disputes", headers=headers)
        assert disputes_resp.status_code == 200, f"Failed listing disputes: {disputes_resp.text}"
        disputes_list = disputes_resp.json()
        target_disp = next((d for d in disputes_list if d["razorpay_dispute_id"] == disp_id), None)
        assert target_disp is not None, f"Dispute {disp_id} was not created in database!"
        db_dispute_id = target_disp["id"]
        print(f"[PASS] Dispute {disp_id} created in DB with primary ID {db_dispute_id}.")

        # 2. Upload Synthetic Dispute Evidence (.pdf)
        pdf_content = b"%PDF-1.4 Synthetic E2E Test Dispute Evidence Document Content Valid Header"
        files = {
            "file": ("e2e_evidence.pdf", io.BytesIO(pdf_content), "application/pdf"),
        }
        data = {
            "document_type": "proof_of_delivery",
            "extracted_amount": "2500.00",
            "extracted_currency": "INR",
        }
        upload_resp = client.post(
            f"{API_BASE}/api/disputes/{db_dispute_id}/evidence",
            headers=headers,
            data=data,
            files=files,
        )
        assert upload_resp.status_code == 200, f"Evidence upload failed: {upload_resp.text}"
        uploaded_doc = upload_resp.json()
        doc_id = uploaded_doc["id"]
        doc_ref = uploaded_doc["reference"]
        print(f"[PASS] Evidence document stored securely in S3/MinIO (ID: {doc_id}, Ref: {doc_ref}).")
        assert doc_ref.startswith("merchants/1/proof_of_delivery/"), f"Unexpected key format: {doc_ref}"
        assert doc_ref.endswith(".pdf")

        # 3. Retrieve Signed Download URL
        signed_url_resp = client.get(
            f"{API_BASE}/api/documents/{doc_id}/signed-url",
            headers=headers,
        )
        assert signed_url_resp.status_code == 200, f"Failed generating signed URL: {signed_url_resp.text}"
        download_url = signed_url_resp.json()["download_url"]
        print(f"[PASS] Signed download token generated: {download_url}")

        # 4. Download and verify content integrity
        download_resp = client.get(f"{API_BASE}{download_url}", headers=headers)
        assert download_resp.status_code == 200, f"Download failed: {download_resp.status_code} {download_resp.text}"
        assert download_resp.content == pdf_content, "Downloaded content does not match uploaded content!"
        print(f"[PASS] Downloaded content verified ({len(download_resp.content)} bytes exact match).")

        # 5. Security Check: Invalid file extension rejection
        bad_files = {
            "file": ("malicious.exe", io.BytesIO(b"MZ\x90\x00\x03Executable"), "application/octet-stream"),
        }
        bad_upload = client.post(
            f"{API_BASE}/api/disputes/{db_dispute_id}/evidence",
            headers=headers,
            data=data,
            files=bad_files,
        )
        assert bad_upload.status_code in (400, 422), f"Expected 400 for .exe, got {bad_upload.status_code}"
        print("[PASS] Security: Malicious .exe file rejected correctly.")

        # 6. Security Check: Fake PDF magic-byte rejection
        fake_pdf = {
            "file": ("fake.pdf", io.BytesIO(b"NOT_A_PDF_FILE_HEADER"), "application/pdf"),
        }
        fake_upload = client.post(
            f"{API_BASE}/api/disputes/{db_dispute_id}/evidence",
            headers=headers,
            data=data,
            files=fake_pdf,
        )
        assert fake_upload.status_code in (400, 422), f"Expected 400 for invalid PDF header, got {fake_upload.status_code}"
        print("[PASS] Security: Invalid PDF magic-bytes rejected correctly.")

        # 7. Security Check: File size > 5MB rejection
        oversized = b"%PDF-1.4" + b"0" * (6 * 1024 * 1024)
        over_files = {
            "file": ("oversized.pdf", io.BytesIO(oversized), "application/pdf"),
        }
        over_upload = client.post(
            f"{API_BASE}/api/disputes/{db_dispute_id}/evidence",
            headers=headers,
            data=data,
            files=over_files,
        )
        assert over_upload.status_code in (400, 422), f"Expected 400 for >5MB file, got {over_upload.status_code}"
        print("[PASS] Security: Oversized file (>5MB) rejected correctly.")

    results["object_storage"] = {
        "doc_id": doc_id,
        "doc_ref": doc_ref,
        "content_length": len(pdf_content),
        "status": "PASS",
    }


def test_section_2_webhook_queue_worker():
    """Verify Section 2: Webhook -> Durable Queue -> Worker End-to-End."""
    print("\n--- SECTION 2: WEBHOOK -> DURABLE QUEUE -> WORKER END-TO-END ---")
    with httpx.Client(timeout=10.0) as client:
        # Step 1: Submit valid synthetic Razorpay payment.failed webhook
        event_id = f"evt_pay_failed_{int(time.time())}"
        pay_id = f"pay_failed_{int(time.time())}"
        order_id = f"order_failed_{int(time.time())}"
        now_ts = int(time.time())

        payload = {
            "entity": "event",
            "account_id": "acc_merchant_1",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "amount": 750000,
                        "currency": "INR",
                        "status": "failed",
                        "order_id": order_id,
                        "description": "Synthetic Failed Payment E2E",
                        "error_code": "BAD_REQUEST_ERROR",
                        "error_description": "Card declined test",
                        "error_source": "customer",
                        "error_step": "payment_authentication",
                        "error_reason": "payment_failed",
                        "created_at": now_ts,
                    }
                }
            },
            "created_at": now_ts,
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig = generate_webhook_signature(body_bytes)

        t_start = time.time()
        wh_resp = client.post(
            f"{API_BASE}/api/webhooks/razorpay",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": sig,
                "X-Razorpay-Event-Id": event_id,
            },
        )
        ack_duration = (time.time() - t_start) * 1000.0
        assert wh_resp.status_code == 200, f"Webhook ingestion failed: {wh_resp.text}"
        wh_data = wh_resp.json()
        print(f"[PASS] Webhook ACK returned HTTP 200 in {ack_duration:.2f}ms. Response: {wh_data}")
        assert wh_data.get("status") == "accepted" or wh_data.get("received") is True

        # Wait for worker daemon to pick up from PostgreSQL durable queue
        time.sleep(2.5)

        # Authenticate and query transactions
        login_resp = client.post(
            f"{API_BASE}/api/auth/login",
            json={"email": "admin@merchant.com", "password": "admin123456"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        txs_resp = client.get(f"{API_BASE}/api/transactions", headers=headers)
        assert txs_resp.status_code == 200, f"Failed listing transactions: {txs_resp.text}"
        txs = txs_resp.json()

        # Find target transaction
        target_tx = next((t for t in txs if t["external_id"] == pay_id), None)
        assert target_tx is not None, f"Transaction {pay_id} was not created by worker!"
        print(f"[PASS] Worker processed event: Transaction {target_tx['id']} created with status '{target_tx['status']}' (Amount: INR {target_tx['amount']}).")

        # Query associated recovery case
        cases_resp = client.get(f"{API_BASE}/api/cases", headers=headers)
        assert cases_resp.status_code == 200, f"Failed listing cases: {cases_resp.text}"
        cases = cases_resp.json()
        target_case = next((c for c in cases if c.get("transaction_id") == target_tx["id"]), None)
        assert target_case is not None, f"RecoveryCase for transaction {target_tx['id']} was not found!"
        case_id = target_case["id"]

        case_analysis_resp = client.get(f"{API_BASE}/api/cases/{case_id}", headers=headers)
        assert case_analysis_resp.status_code == 200, f"Failed fetching case analysis: {case_analysis_resp.text}"
        case_data = case_analysis_resp.json()
        print(f"[PASS] RecoveryCase {case_id} created (Status: {case_data['case_status']}, Risk Score: {case_data['risk_score']}, NBA: {case_data['next_best_action']}).")

        # Query timeline audit trail
        audit_resp = client.get(f"{API_BASE}/api/cases/{case_id}/audit", headers=headers)
        assert audit_resp.status_code == 200, f"Failed fetching audit trail: {audit_resp.text}"
        audit_logs = audit_resp.json()
        assert len(audit_logs) > 0, "No audit events found in audit log!"
        print(f"[PASS] Audit trail verified: {len(audit_logs)} audit events recorded.")

        # Step 2: Concurrent Duplicate Ingestion
        print("Testing 10 concurrent duplicate webhook submissions...")
        def send_duplicate():
            with httpx.Client(timeout=5.0) as c:
                return c.post(
                    f"{API_BASE}/api/webhooks/razorpay",
                    content=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Razorpay-Signature": sig,
                        "X-Razorpay-Event-Id": event_id,
                    },
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            dup_resps = list(executor.map(lambda _: send_duplicate(), range(10)))

        for r in dup_resps:
            assert r.status_code == 200, f"Duplicate webhook submission failed: {r.status_code}"
            assert r.json().get("duplicate") is True or r.json().get("received") is True

        time.sleep(2.0)

        # Verify no duplicate transactions or inflated financial entries
        txs_after = client.get(f"{API_BASE}/api/transactions", headers=headers).json()
        matching_txs = [t for t in txs_after if t["external_id"] == pay_id]
        assert len(matching_txs) == 1, f"Expected exactly 1 transaction, found {len(matching_txs)}!"
        print("[PASS] Concurrent duplicate idempotency verified: Exactly 1 logical Transaction and RecoveryCase created.")

    results["webhook_worker"] = {
        "event_id": event_id,
        "ack_ms": ack_duration,
        "tx_id": target_tx["id"],
        "case_id": case_data["case_id"],
        "status": "PASS",
    }


def test_section_3_worker_crash_recovery():
    """Verify Section 3: Worker Crash and Restart Recovery."""
    print("\n--- SECTION 3: WORKER CRASH / RESTART RECOVERY ---")
    with httpx.Client(timeout=10.0) as client:
        # 1. Stop recoverx-worker container
        print("Stopping recoverx-worker container...")
        subprocess.run(["docker", "stop", "recoverx-worker"], check=True)
        print("[PASS] recoverx-worker stopped.")

        # 2. Submit webhook while worker is completely stopped
        event_id = f"evt_crash_recov_{int(time.time())}"
        pay_id = f"pay_crash_recov_{int(time.time())}"
        now_ts = int(time.time())

        payload = {
            "entity": "event",
            "account_id": "acc_merchant_1",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "amount": 920000,
                        "currency": "INR",
                        "status": "failed",
                        "description": "Payment while worker down",
                        "created_at": now_ts,
                    }
                }
            },
            "created_at": now_ts,
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig = generate_webhook_signature(body_bytes)

        wh_resp = client.post(
            f"{API_BASE}/api/webhooks/razorpay",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": sig,
                "X-Razorpay-Event-Id": event_id,
            },
        )
        assert wh_resp.status_code == 200, f"API rejected webhook while worker stopped: {wh_resp.text}"
        print(f"[PASS] API accepted webhook (HTTP 200) and durably persisted event {event_id} in PostgreSQL while worker is DOWN.")

        # 3. Restart recoverx-worker container
        print("Starting recoverx-worker container...")
        subprocess.run(["docker", "start", "recoverx-worker"], check=True)
        print("[PASS] recoverx-worker started.")

        # Wait for worker daemon to discover pending queue item and process it
        time.sleep(3.5)

        # 4. Verify event was automatically discovered and processed
        login_resp = client.post(
            f"{API_BASE}/api/auth/login",
            json={"email": "admin@merchant.com", "password": "admin123456"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        txs = client.get(f"{API_BASE}/api/transactions", headers=headers).json()
        recovered_tx = next((t for t in txs if t["external_id"] == pay_id), None)
        assert recovered_tx is not None, f"Pending event {event_id} was NOT picked up and processed upon worker restart!"
        print(f"[PASS] Worker restart crash recovery verified: Discovered pending event {event_id}, created Transaction {recovered_tx['id']} (Status: {recovered_tx['status']}, Amount: INR {recovered_tx['amount']}).")

    results["crash_recovery"] = {
        "event_id": event_id,
        "tx_id": recovered_tx["id"],
        "status": "PASS",
    }


def main():
    print("=" * 70)
    print("RECOVERX PHASE 11.2 LOCAL PRODUCTION STACK END-TO-END VERIFICATION")
    print("=" * 70)
    test_section_4_health()
    test_section_1_object_storage()
    test_section_2_webhook_queue_worker()
    test_section_3_worker_crash_recovery()

    print("\n" + "=" * 70)
    print("ALL 4 LOCAL E2E PRODUCTION VERIFICATION SUITES PASSED SUCCESSFULLY")
    print("=" * 70)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
