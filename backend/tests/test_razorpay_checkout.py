import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

TEST_DB = Path(tempfile.gettempdir()) / "recoverx_razorpay_checkout_tests.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_mock_12345"
os.environ["RAZORPAY_KEY_SECRET"] = "rzp_test_secret_abc123"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "rzp_webhook_secret_xyz789"

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.database.connection import engine
from app.database.session import SessionLocal
from app.main import app
from app.models.audit_log import AuditLog
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.services.razorpay_service import RazorpayService


def create_mock_razorpay_client(order_id: str = "order_Pt6g1x8j9KlmNo", amount: int = 50000, currency: str = "INR", status_code: int = 200, err_msg: str | None = None) -> MagicMock:
    mock_client_instance = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if err_msg:
        mock_resp.json.return_value = {"error": {"code": "BAD_REQUEST_ERROR", "description": err_msg}}
        mock_resp.text = err_msg
    else:
        mock_resp.json.return_value = {
            "id": order_id,
            "entity": "order",
            "amount": amount,
            "amount_paid": 0,
            "amount_due": amount,
            "currency": currency,
            "receipt": f"recoverx_test_{uuid4().hex[:8]}",
            "status": "created",
            "notes": {"source": "RecoverX", "environment": "test"},
            "created_at": 1735689600,
        }
    mock_client_instance.__enter__.return_value.post.return_value = mock_resp
    return mock_client_instance



class RazorpayCheckoutIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        get_settings.cache_clear()
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.service = RazorpayService()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        engine.dispose()
        if TEST_DB.exists():
            TEST_DB.unlink()

    def test_01_test_key_validation_and_live_key_rejection(self) -> None:
        """1. Test that live Razorpay keys and missing credentials are strictly validated."""
        live_settings = Settings(razorpay_key_id="rzp_live_realprodkey123", razorpay_key_secret="secret")
        service = RazorpayService(settings=live_settings)
        with self.assertRaises(Exception) as ctx:
            service.validate_test_mode_configuration()
        self.assertIn("Only Razorpay Test Mode", str(ctx.exception.detail))

        # Missing credentials should be rejected
        unconfigured_settings = Settings(razorpay_key_id="", razorpay_key_secret="")
        unconfigured_service = RazorpayService(settings=unconfigured_settings)
        with self.assertRaises(Exception) as ctx:
            unconfigured_service.validate_test_mode_configuration()
        self.assertIn("not configured", str(ctx.exception.detail))

        # Valid test mode key and secret should pass validation
        valid_settings = Settings(razorpay_key_id="rzp_test_1234567890", razorpay_key_secret="secret")
        valid_service = RazorpayService(settings=valid_settings)
        valid_service.validate_test_mode_configuration()

    @patch("app.services.razorpay_service.httpx.Client")
    def test_02_create_order_success_calls_real_api_and_persists_order_id(self, mock_client_cls: MagicMock) -> None:
        """2. Test creating an order calls the real Razorpay Orders API and persists the real order ID."""
        expected_order_id = "order_Pt6g1x8j9KlmNo"
        mock_client_cls.return_value = create_mock_razorpay_client(order_id=expected_order_id, amount=50000, currency="INR")

        payload = {
            "amount": "500.00",
            "currency": "INR",
            "receipt": "rcpt_test_01",
            "customer_name": "Acme Test Corp",
            "customer_email": "billing@acmetest.com",
        }
        res = self.client.post("/api/payments/create-order", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()

        # Must be the REAL Razorpay format (order_...), NOT order_test_...
        self.assertEqual(data["order_id"], expected_order_id)
        self.assertFalse(data["order_id"].startswith("order_test_"))
        self.assertEqual(data["amount"], "500.00")
        self.assertEqual(data["currency"], "INR")
        self.assertEqual(data["amount_subunits"], 50000)  # 500.00 * 100 paise

        # Verify transaction persistence in database
        with SessionLocal() as db:
            tx = db.scalar(select(Transaction).where(Transaction.order_id == expected_order_id))
            self.assertIsNotNone(tx)
            self.assertEqual(tx.amount, Decimal("500.00"))
            self.assertEqual(tx.status, "created")

    @patch("app.services.razorpay_service.httpx.Client")
    def test_03_create_order_zero_decimal_currency_subunits(self, mock_client_cls: MagicMock) -> None:
        """3. Test JPY zero-decimal currency subunit conversion."""
        mock_client_cls.return_value = create_mock_razorpay_client(order_id="order_jpy_123", amount=15000, currency="JPY")

        payload = {
            "amount": "15000",
            "currency": "JPY",
        }
        res = self.client.post("/api/payments/create-order", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["amount_subunits"], 15000)

    def test_04_create_order_invalid_amount_rejection(self) -> None:
        """4. Test that negative or zero amounts are rejected with 422."""
        res_zero = self.client.post("/api/payments/create-order", json={"amount": "0", "currency": "INR"})
        self.assertEqual(res_zero.status_code, 422)

        res_neg = self.client.post("/api/payments/create-order", json={"amount": "-250.00", "currency": "INR"})
        self.assertEqual(res_neg.status_code, 422)

    def test_05_create_order_invalid_currency_rejection(self) -> None:
        """5. Test that invalid currency code is rejected with 422."""
        res = self.client.post("/api/payments/create-order", json={"amount": "5000", "currency": "INVALID"})
        self.assertEqual(res.status_code, 422)

    @patch("app.services.razorpay_service.httpx.Client")
    def test_06_create_order_razorpay_api_failure_handled_safely(self, mock_client_cls: MagicMock) -> None:
        """6. Test safe handling when Razorpay API returns an error."""
        mock_client_cls.return_value = create_mock_razorpay_client(status_code=401, err_msg="Authentication failed")

        res = self.client.post("/api/payments/create-order", json={"amount": "100.00", "currency": "INR"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication failed", res.json()["detail"])

    @patch("app.services.razorpay_service.httpx.Client")
    def test_07_payment_signature_verification_success(self, mock_client_cls: MagicMock) -> None:
        """7. Test server-side payment signature verification against stored order."""
        order_id = "order_Pt7h2y9k0LmnOp"
        mock_client_cls.return_value = create_mock_razorpay_client(order_id=order_id, amount=1200000, currency="INR")

        # 1. Create order first
        create_res = self.client.post("/api/payments/create-order", json={"amount": "12000.00", "currency": "INR"})
        self.assertEqual(create_res.status_code, 201)
        payment_id = "pay_test_verified_999"

        # 2. Generate signature using secret
        valid_signature = self.service.create_test_payment_signature(order_id, payment_id)

        # 3. Call verify endpoint
        verify_res = self.client.post(
            "/api/payments/verify",
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": valid_signature,
            },
        )
        self.assertEqual(verify_res.status_code, 200)
        verify_data = verify_res.json()
        self.assertTrue(verify_data["verified"])
        self.assertEqual(verify_data["status"], "payment_verified")

        # 4. Verify transaction status was updated in database
        with SessionLocal() as db:
            tx = db.scalar(select(Transaction).where(Transaction.order_id == order_id))
            self.assertIsNotNone(tx)
            self.assertEqual(tx.external_id, payment_id)
            self.assertEqual(tx.status, "payment_verified")

    @patch("app.services.razorpay_service.httpx.Client")
    def test_08_payment_signature_verification_invalid_signature(self, mock_client_cls: MagicMock) -> None:
        """8. Test rejection of forged/invalid payment signature."""
        order_id = "order_Pt8i3z0l1MnoPq"
        mock_client_cls.return_value = create_mock_razorpay_client(order_id=order_id, amount=800000, currency="INR")

        create_res = self.client.post("/api/payments/create-order", json={"amount": "8000.00", "currency": "INR"})
        self.assertEqual(create_res.status_code, 201)

        verify_res = self.client.post(
            "/api/payments/verify",
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": "pay_test_bad_sig",
                "razorpay_signature": "forged_invalid_signature_hex_code",
            },
        )
        self.assertEqual(verify_res.status_code, 400)
        self.assertIn("Invalid payment signature", verify_res.json()["detail"])

    def test_09_payment_signature_unknown_order_not_found(self) -> None:
        """9. Test rejection when client supplies an unknown order ID."""
        verify_res = self.client.post(
            "/api/payments/verify",
            json={
                "razorpay_order_id": "order_non_existent_9999",
                "razorpay_payment_id": "pay_test_unknown",
                "razorpay_signature": "sig_dummy",
            },
        )
        self.assertEqual(verify_res.status_code, 404)

    @patch("app.services.razorpay_service.httpx.Client")
    def test_10_webhook_payment_captured_automatic_intelligence_analysis(self, mock_client_cls: MagicMock) -> None:
        """10. Test full flow: Order -> Webhook payment.captured -> Automatic Case & Risk Analysis."""
        order_id = "order_Pt9j4a1m2NopQr"
        mock_client_cls.return_value = create_mock_razorpay_client(order_id=order_id, amount=25000000, currency="INR")

        # 1. Create order for a high-value payment
        create_res = self.client.post("/api/payments/create-order", json={"amount": "250000.00", "currency": "INR"})
        self.assertEqual(create_res.status_code, 201)
        payment_id = f"pay_captured_{order_id[-8:]}"

        # 2. Simulate Razorpay server-to-server webhook
        payload = {
            "event_id": f"evt_{order_id[-8:]}",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "order_id": order_id,
                        "amount": 25000000,  # 250,000 INR in paise
                        "currency": "INR",
                        "status": "captured",
                        "method": "card",
                        "country_code": "IN",
                        "created_at": 1735689600,
                    }
                }
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        webhook_res = self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": self.service.create_test_signature(body)},
        )
        self.assertEqual(webhook_res.status_code, 200)

        # 3. Check live order status endpoint for automatic intelligence calculation
        status_res = self.client.get(f"/api/payments/order/{order_id}/status")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()

        self.assertEqual(status_data["order_id"], order_id)
        self.assertEqual(status_data["payment_id"], payment_id)
        self.assertIsNotNone(status_data["transaction_id"])
        self.assertIsNotNone(status_data["case_id"])
        self.assertIsNotNone(status_data["risk_score"])
        self.assertIsNotNone(status_data["revenue_at_risk"])
        self.assertIsNotNone(status_data["recovery_probability"])
        self.assertIsNotNone(status_data["next_best_action"])

        # Timeline verification
        timeline_keys = [t["key"] for t in status_data["timeline"]]
        self.assertIn("initiated", timeline_keys)
        self.assertIn("webhook", timeline_keys)
        self.assertIn("analyzed", timeline_keys)
        self.assertIn("action", timeline_keys)

    @patch("app.services.razorpay_service.httpx.Client")
    def test_11_webhook_payment_failed(self, mock_client_cls: MagicMock) -> None:
        """11. Test webhook payment.failed event."""
        order_id = "order_Pt0k5b2n3OpqRs"
        mock_client_cls.return_value = create_mock_razorpay_client(order_id=order_id, amount=100000, currency="INR")

        create_res = self.client.post("/api/payments/create-order", json={"amount": "1000.00", "currency": "INR"})
        self.assertEqual(create_res.status_code, 201)
        payment_id = f"pay_failed_{order_id[-8:]}"

        payload = {
            "event_id": f"evt_failed_{order_id[-8:]}",
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "order_id": order_id,
                        "amount": 100000,
                        "currency": "INR",
                        "status": "failed",
                        "method": "upi",
                    }
                }
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        webhook_res = self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": self.service.create_test_signature(body)},
        )
        self.assertEqual(webhook_res.status_code, 200)

        with SessionLocal() as db:
            tx = db.scalar(select(Transaction).where(Transaction.order_id == order_id))
            self.assertEqual(tx.status, "failed")

    def test_12_order_status_not_found(self) -> None:
        """12. Test 404 response for non-existent order status."""
        res = self.client.get("/api/payments/order/order_unknown_12345/status")
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()


