"""Unit and integration tests for Phase 7 Live Transaction Test Mode."""

import os
import tempfile
import unittest
from decimal import Decimal

# Ensure test DB environment
TEST_DB = __import__("pathlib").Path(tempfile.gettempdir()) / "recoverx_phase7_tests.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_example"
os.environ["RAZORPAY_KEY_SECRET"] = "test_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"

from fastapi.testclient import TestClient

import app.models  # noqa
from app.core.config import get_settings
from app.database.connection import Base, engine
from app.database.session import SessionLocal
from app.main import app
from app.models.recovery_case import RecoveryCase
from app.models.transaction import Transaction


class LiveTransactionTestModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__()

    def setUp(self) -> None:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        get_settings.cache_clear()
        self.db = SessionLocal()

    def tearDown(self) -> None:
        self.db.close()


    def test_country_india_inr(self) -> None:
        """1. Test India (IN) -> INR standard mapping and alignment."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 580000,
                "currency": "INR",
                "country_code": "IN",
                "payment_status": "received",
                "customer_information_complete": False,
                "document_available": True,
                "invoice_amount": 580000,
                "invoice_currency": "INR",
                "invoice_reference": "INV-DEMO-580K",
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["currency"], "INR")
        self.assertEqual(data["country_code"], "IN")
        self.assertFalse(data["is_cross_border_mismatch"])
        self.assertEqual(Decimal(str(data["amount"])), Decimal("580000.00"))
        self.assertTrue(data["is_high_value"])
        self.assertEqual(Decimal(str(data["risk_score"])), Decimal("45.00"))
        self.assertEqual(Decimal(str(data["revenue_at_risk"])), Decimal("261000.00"))
        self.assertEqual(Decimal(str(data["recovery_probability"])), Decimal("0.820"))
        self.assertEqual(data["next_best_action"], "REQUEST_INFORMATION")

    def test_country_united_states_usd(self) -> None:
        """2. Test United States (US) -> USD default alignment."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 25000,
                "currency": "USD",
                "country_code": "US",
                "payment_status": "captured",
                "customer_information_complete": True,
                "document_available": True,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["country_code"], "US")
        self.assertFalse(data["is_cross_border_mismatch"])
        self.assertTrue(data["is_high_value"])

    def test_country_united_kingdom_gbp(self) -> None:
        """3. Test United Kingdom (GB) -> GBP default alignment."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 15000,
                "currency": "GBP",
                "country_code": "GB",
                "payment_status": "captured",
                "customer_information_complete": True,
                "document_available": True,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["currency"], "GBP")
        self.assertEqual(data["country_code"], "GB")
        self.assertFalse(data["is_cross_border_mismatch"])

    def test_country_japan_jpy(self) -> None:
        """4. Test Japan (JP) -> JPY default alignment."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 1500000,
                "currency": "JPY",
                "country_code": "JP",
                "payment_status": "captured",
                "customer_information_complete": True,
                "document_available": True,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["currency"], "JPY")
        self.assertEqual(data["country_code"], "JP")
        self.assertFalse(data["is_cross_border_mismatch"])

    def test_country_germany_eur(self) -> None:
        """5. Test Germany (DE) -> EUR default alignment."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 50000,
                "currency": "EUR",
                "country_code": "DE",
                "payment_status": "captured",
                "customer_information_complete": True,
                "document_available": True,
                "invoice_amount": 50000,
                "invoice_currency": "EUR",
                "invoice_reference": "INV-EUR-50K",
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["country_code"], "DE")
        self.assertFalse(data["is_cross_border_mismatch"])
        self.assertTrue(data["is_high_value"])
        self.assertEqual(Decimal(str(data["risk_score"])), Decimal("25.00"))
        self.assertEqual(data["readiness_status"], "READY")
        self.assertEqual(Decimal(str(data["revenue_at_risk"])), Decimal("12500.00"))

    def test_manual_currency_override(self) -> None:
        """6. Test manual currency override (e.g. US customer transacting in EUR)."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 25000,
                "currency": "EUR",
                "country_code": "US",
                "payment_status": "captured",
                "customer_information_complete": True,
                "document_available": True,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["country_code"], "US")
        # Kept exact amount and currency without conversion
        self.assertEqual(Decimal(str(data["amount"])), Decimal("25000.00"))
        # Flagged as cross border mismatch
        self.assertTrue(data["is_cross_border_mismatch"])
        self.assertIn("differs from transaction currency", data["currency_note"])

    def test_country_currency_mismatch_allowed_and_flagged(self) -> None:
        """7. Test that cross-border mismatch is allowed, processed safely, and flagged."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 100000,
                "currency": "USD",
                "country_code": "IN",
                "payment_status": "received",
                "customer_information_complete": True,
                "document_available": True,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["country_code"], "IN")
        self.assertTrue(data["is_cross_border_mismatch"])
        self.assertIn("IN", data["currency_note"])
        self.assertIn("USD", data["currency_note"])

    def test_invalid_country_rejected(self) -> None:
        """8. Test rejection of unapproved / invalid country codes."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 5000,
                "currency": "USD",
                "country_code": "ZZ",
            },
        )
        self.assertEqual(res.status_code, 422)

    def test_invalid_currency_rejected(self) -> None:
        """9. Test rejection of unapproved / invalid currency format."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 5000,
                "currency": "INVALID",
                "country_code": "US",
            },
        )
        self.assertEqual(res.status_code, 422)

    def test_usd_5_billion_large_transaction_decimal_precision(self) -> None:
        """10. Test USD 5,000,000,000 large transaction with exact Decimal arithmetic."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 5000000000,
                "currency": "USD",
                "country_code": "US",
                "payment_status": "received",
                "customer_information_complete": False,
                "document_available": True,
                "invoice_amount": 5000000000,
                "invoice_currency": "USD",
                "invoice_reference": "INV-GLOBAL-5B",
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(Decimal(str(data["amount"])), Decimal("5000000000.00"))
        self.assertTrue(data["is_high_value"])
        # Risk score: 20 (high value) + 20 (incomplete info) + 5 (no history) = 45
        self.assertEqual(Decimal(str(data["risk_score"])), Decimal("45.00"))
        # Revenue at risk: 5,000,000,000 * 0.45 = 2,250,000,000
        self.assertEqual(Decimal(str(data["revenue_at_risk"])), Decimal("2250000000.00"))
        self.assertEqual(data["readiness_status"], "AT_RISK")
        self.assertEqual(data["next_best_action"], "REQUEST_INFORMATION")

    def test_small_transaction(self) -> None:
        """11. Test small transaction below high-value threshold."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 150,
                "currency": "USD",
                "country_code": "US",
                "payment_status": "captured",
                "customer_information_complete": True,
                "document_available": True,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertFalse(data["is_high_value"])
        # Risk score is only 5 from zero history
        self.assertEqual(Decimal(str(data["risk_score"])), Decimal("5.00"))
        self.assertEqual(data["readiness_status"], "READY")
        self.assertEqual(data["next_best_action"], "NO_ACTION")

    def test_negative_amount(self) -> None:
        """12. Test rejection of negative or zero amount."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": -500,
                "currency": "USD",
                "country_code": "US",
            },
        )
        self.assertEqual(res.status_code, 422)

    def test_missing_required_fields(self) -> None:
        """13. Test rejection when required amount is missing."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "currency": "USD",
                "country_code": "US",
            },
        )
        self.assertEqual(res.status_code, 422)

    def test_invoice_amount_mismatch_in_subsequent_resolution(self) -> None:
        """14. Test that test transaction seamlessly executes customer resolution and fails on mismatch."""
        # 1. Create test transaction
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 10000,
                "currency": "USD",
                "country_code": "US",
                "payment_status": "received",
                "customer_information_complete": False,
                "document_available": True,
            },
        )
        self.assertEqual(res.status_code, 201)
        case_id = res.json()["case_id"]

        # 2. Customer submits mismatching amount (9000 instead of 10000)
        res_resolve = self.client.post(
            f"/api/customers/cases/{case_id}/resolve",
            json={
                "customer_name": "John Doe",
                "customer_email": "john.doe@enterprise.com",
                "country_code": "US",
                "invoice_amount": 9000,
                "invoice_currency": "USD",
                "invoice_reference": "INV-MISMATCH-001",
                "invoice_date": "2026-01-20",
            },
        )
        self.assertEqual(res_resolve.status_code, 200)
        val_data = res_resolve.json()
        self.assertEqual(val_data["status"], "FAIL")
        self.assertIn("Critical financial or identity inconsistency", val_data["overall_reason"])

    def test_dynamically_generated_recovery_case(self) -> None:
        """15. Test that a real database RecoveryCase and Transaction are persisted."""
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 750000,
                "currency": "INR",
                "country_code": "IN",
                "payment_status": "received",
                "customer_information_complete": False,
                "document_available": False,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        case_id = data["case_id"]
        txn_id = data["transaction_id"]

        # Verify DB records
        txn = self.db.get(Transaction, txn_id)
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, Decimal("750000.00"))

        case = self.db.get(RecoveryCase, case_id)
        self.assertIsNotNone(case)
        self.assertEqual(case.transaction_id, txn_id)

    def test_dynamic_revenue_at_risk_calculation(self) -> None:
        """16. Test dynamic revenue-at-risk calculation across various combinations."""
        # Missing doc + missing profile -> Risk Score: 20 (high value) + 20 (profile) + 25 (doc) + 5 (history) = 70 (HIGH_RISK)
        res = self.client.post(
            "/api/transactions/test",
            json={
                "amount": 200000,
                "currency": "INR",
                "country_code": "IN",
                "payment_status": "received",
                "customer_information_complete": False,
                "document_available": False,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(Decimal(str(data["risk_score"])), Decimal("70.00"))
        # 200000 * 0.70 = 140000
        self.assertEqual(Decimal(str(data["revenue_at_risk"])), Decimal("140000.00"))
        self.assertEqual(data["readiness_status"], "HIGH_RISK")



if __name__ == "__main__":
    unittest.main()
