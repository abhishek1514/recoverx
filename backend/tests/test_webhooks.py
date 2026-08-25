import json
import os
import tempfile
import unittest
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "recoverx_webhook_tests.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_example"
os.environ["RAZORPAY_KEY_SECRET"] = "test_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"

from fastapi.testclient import TestClient

from app.database.connection import engine
from app.database.session import SessionLocal
from app.main import app
from app.models.transaction import Transaction
from app.models.webhook_event import WebhookEvent
from app.models.recovery_case import RecoveryCase
from app.services.razorpay_service import RazorpayService


def payment_payload(event_id: str, payment_id: str, payment_status: str = "captured") -> dict:
    return {
        "event_id": event_id,
        "event": f"payment.{payment_status}",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": "order_test_123",
                    "amount": 12550,
                    "currency": "INR",
                    "status": payment_status,
                    "method": "upi",
                    "customer_id": "cust_test_123",
                    "created_at": 1735689600,
                    "card": {"number": "4111111111111111", "cvv": "123"},
                }
            }
        },
    }


class RazorpayWebhookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.service = RazorpayService()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        engine.dispose()
        if TEST_DB.exists():
            TEST_DB.unlink()

    def post_signed(self, payload: dict):
        body = json.dumps(payload, separators=(",", ":")).encode()
        return self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": self.service.create_test_signature(body)},
        )

    def test_valid_webhook(self) -> None:
        response = self.post_signed(payment_payload("evt_valid", "pay_valid"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["duplicate"])
        with SessionLocal() as db:
            transaction = db.query(Transaction).filter_by(external_id="pay_valid").one()
            self.assertIsNotNone(db.query(RecoveryCase).filter_by(transaction_id=transaction.id).one_or_none())

    def test_invalid_signature(self) -> None:
        response = self.client.post(
            "/api/webhooks/razorpay",
            content=json.dumps(payment_payload("evt_bad", "pay_bad")),
            headers={"X-Razorpay-Signature": "not-a-valid-signature"},
        )
        self.assertEqual(response.status_code, 401)

    def test_duplicate_webhook(self) -> None:
        payload = payment_payload("evt_duplicate", "pay_duplicate")
        self.assertEqual(self.post_signed(payload).status_code, 200)
        response = self.post_signed(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["duplicate"])
        with SessionLocal() as db:
            self.assertEqual(db.query(Transaction).filter_by(external_id="pay_duplicate").count(), 1)
            self.assertEqual(db.query(WebhookEvent).filter_by(event_id="evt_duplicate").count(), 1)

    def test_malformed_payload(self) -> None:
        body = b"not-json"
        response = self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": self.service.create_test_signature(body)},
        )
        self.assertEqual(response.status_code, 400)

    def test_transaction_creation(self) -> None:
        self.post_signed(payment_payload("evt_create", "pay_create"))
        with SessionLocal() as db:
            transaction = db.query(Transaction).filter_by(external_id="pay_create").one()
            self.assertEqual(str(transaction.amount), "125.50")
            self.assertEqual(transaction.order_id, "order_test_123")
            self.assertEqual(transaction.event_type, "payment.captured")

    def test_transaction_update(self) -> None:
        self.post_signed(payment_payload("evt_update_1", "pay_update", "authorized"))
        self.post_signed(payment_payload("evt_update_2", "pay_update", "captured"))
        with SessionLocal() as db:
            transaction = db.query(Transaction).filter_by(external_id="pay_update").one()
            self.assertEqual(transaction.status, "captured")
            self.assertEqual(db.query(Transaction).filter_by(external_id="pay_update").count(), 1)


if __name__ == "__main__":
    unittest.main()
