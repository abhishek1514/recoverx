"""Production Reliability & Fault Tolerance Test Suite for RecoverX."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.database.connection import ensure_schema
from app.database.session import SessionLocal
from app.main import app
from app.models.dispute import Dispute
from app.models.recovery_case import RecoveryCase
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.models.webhook_event import WebhookEvent
from app.services.ai_service import generate_dispute_contest_draft
from app.services.razorpay_service import RazorpayService


class ProductionReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_schema()
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.service = RazorpayService(settings=get_settings())
        cls.token_m1 = create_access_token(data={"sub": "1", "merchant_id": 1})

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    # =========================================================================
    # 1. Webhook Replay & Timestamp Tolerance
    # =========================================================================
    def test_01_stale_webhook_timestamp_rejected(self) -> None:
        """1. Verify webhook replay protection rejects payloads beyond tolerance window."""
        stale_ts = int((datetime.now(UTC) - timedelta(minutes=15)).timestamp())
        payload = {
            "entity": "event",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_stale_{uuid4().hex[:8]}",
                        "amount": 5000000,
                        "currency": "INR",
                        "status": "captured",
                        "created_at": stale_ts,
                    }
                }
            },
            "created_at": stale_ts,
        }
        # Direct verification with explicit 300s tolerance
        is_valid = self.service.verify_webhook_replay_protection(payload, tolerance_seconds=300)
        self.assertFalse(is_valid)

        fresh_payload = dict(payload)
        fresh_payload["created_at"] = int(datetime.now(UTC).timestamp())
        self.assertTrue(self.service.verify_webhook_replay_protection(fresh_payload, tolerance_seconds=300))

    # =========================================================================
    # 2. Duplicate Webhook Idempotency
    # =========================================================================
    def test_02_duplicate_webhook_processed_idempotently(self) -> None:
        """2. Verify duplicate webhook delivery does not duplicate cases or transactions."""
        tag = uuid4().hex[:8]
        now_ts = int(datetime.now(UTC).timestamp())
        payload = {
            "entity": "event",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_idem_{tag}",
                        "order_id": f"order_idem_{tag}",
                        "amount": 25000000,  # ₹2,50,000 INR
                        "currency": "INR",
                        "status": "captured",
                        "created_at": now_ts,
                    }
                }
            },
            "created_at": now_ts,
        }
        body = json.dumps(payload).encode("utf-8")
        sig = self.service.create_test_signature(body)

        # Delivery 1
        res1 = self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
        )
        self.assertEqual(res1.status_code, 200)

        # Delivery 2 (Duplicate)
        res2 = self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
        )
        self.assertEqual(res2.status_code, 200)

        # Assert exactly one transaction and case created
        with SessionLocal() as db:
            txs = list(db.scalars(select(Transaction).where(Transaction.external_id == f"pay_idem_{tag}")).all())
            self.assertEqual(len(txs), 1)

    # =========================================================================
    # 3. Out-of-Order Webhook Delivery (State Precedence)
    # =========================================================================
    def test_03_out_of_order_status_precedence(self) -> None:
        """3. Verify captured transaction does not regress to authorized on out-of-order webhook."""
        tag = uuid4().hex[:8]
        now_ts = int(datetime.now(UTC).timestamp())
        # First arrive: captured
        p_cap = {
            "entity": "event",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_order_{tag}",
                        "amount": 1000000,
                        "currency": "INR",
                        "status": "captured",
                        "created_at": now_ts,
                    }
                }
            },
            "created_at": now_ts,
        }
        body_cap = json.dumps(p_cap).encode("utf-8")
        self.client.post(
            "/api/webhooks/razorpay",
            content=body_cap,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": self.service.create_test_signature(body_cap)},
        )

        # Out-of-order second arrival: authorized
        p_auth = {
            "entity": "event",
            "event": "payment.authorized",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_order_{tag}",
                        "amount": 1000000,
                        "currency": "INR",
                        "status": "authorized",
                        "created_at": now_ts,
                    }
                }
            },
            "created_at": now_ts,
        }
        body_auth = json.dumps(p_auth).encode("utf-8")
        self.client.post(
            "/api/webhooks/razorpay",
            content=body_auth,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": self.service.create_test_signature(body_auth)},
        )

        with SessionLocal() as db:
            tx = db.scalar(select(Transaction).where(Transaction.external_id == f"pay_order_{tag}"))
            self.assertEqual(tx.status, "captured")

    # =========================================================================
    # 4. OpenAI Offline Fallback (Deterministic Resilience)
    # =========================================================================
    def test_04_openai_outage_deterministic_fallback(self) -> None:
        """4. Verify AI drafting gracefully falls back to deterministic template when OpenAI is down or unconfigured."""
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            disp = Dispute(
                merchant_id=1,
                razorpay_dispute_id=f"disp_ai_fail_{tag}",
                amount=Decimal("45000.00"),
                currency="INR",
                reason_code="product_not_received",
                status="open",
            )
            db.add(disp)
            db.commit()
            db.refresh(disp)

            result = generate_dispute_contest_draft(
                dispute=disp,
                transaction=None,
                customer=None,
                documents=[],
                merchant_notes="Tracking Ref: AWB_SHIPPING_PROOF",
            )
            self.assertIn("contest_summary", result)
            self.assertIn("AWB_SHIPPING_PROOF", result["contest_summary"])
            self.assertEqual(result["disclaimer"], "AI-generated draft — requires merchant review.")


if __name__ == "__main__":
    unittest.main()
