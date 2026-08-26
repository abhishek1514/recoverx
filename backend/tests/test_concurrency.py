"""Concurrency & Race Condition Resilience Test Suite for RecoverX."""

from __future__ import annotations

import concurrent.futures
import json
from datetime import UTC, datetime
from decimal import Decimal
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.database.connection import ensure_schema
from app.database.session import SessionLocal
from app.main import app
from app.models.transaction import Transaction
from app.services.razorpay_service import RazorpayService


class ConcurrencyTests(unittest.TestCase):
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

    def test_01_concurrent_duplicate_webhooks(self) -> None:
        """1. Verify concurrent submission of the same webhook payload does not cause race conditions or duplicates."""
        tag = uuid4().hex[:8]
        now_ts = int(datetime.now(UTC).timestamp())
        payload = {
            "entity": "event",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_conc_{tag}",
                        "order_id": f"order_conc_{tag}",
                        "amount": 1000000,
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

        def send_webhook():
            return self.client.post(
                "/api/webhooks/razorpay",
                content=body,
                headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(send_webhook) for _ in range(5)]
            responses = [f.result() for f in futures]

        for r in responses:
            self.assertEqual(r.status_code, 200)

        # Assert exactly one transaction record in database
        with SessionLocal() as db:
            txs = list(db.scalars(select(Transaction).where(Transaction.external_id == f"pay_conc_{tag}")).all())
            self.assertEqual(len(txs), 1)


if __name__ == "__main__":
    unittest.main()

