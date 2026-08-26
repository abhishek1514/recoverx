"""Targeted Test Suite for Webhook / Payment-State Exception Recovery (RecoverX Phase 8.1).

Validates:
1. Webhook processing failure in DLQ -> RecoveryCase creation
2. Provider / local state mismatch -> RecoveryCase creation
3. Provider / local state agreement -> No RecoveryCase created
4. Duplicate detection -> Exactly one logical RecoveryCase
5. Existing RecoveryCase -> No duplicate case generated
6. Resync succeeds -> Case marked 'recovered', stage 'resolved', amount_at_risk 0.00
7. Resync failure -> Case remains unresolved with audit log
8. Cross-merchant access -> Strict rejection (HTTP 403/404)
9. Financial Decimal arithmetic -> Exact Decimal precision with zero float casting
10. Existing exception types -> Untouched and frozen
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.security import create_access_token
from app.database.connection import Base
from app.database.session import get_db
from app.main import app
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.recovery_case import RecoveryCase
from app.models.transaction import Transaction
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.services.razorpay_service import RazorpayService
from app.services.webhook_recovery_service import WebhookRecoveryService


class WebhookPaymentStateRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        Base.metadata.create_all(bind=self.engine)
        self.db = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Seed Merchant 1 and Merchant 2
        self.merchant1 = Merchant(id=1, name="Test Merchant 1", country_code="IN", currency="INR", is_active=True)
        self.merchant2 = Merchant(id=2, name="Test Merchant 2", country_code="IN", currency="INR", is_active=True)
        self.db.add_all([self.merchant1, self.merchant2])

        # Seed Users
        self.user1 = User(id=1, merchant_id=1, email="admin@m1.com", hashed_password="hash1", role="admin", is_active=True)
        self.user2 = User(id=2, merchant_id=2, email="admin@m2.com", hashed_password="hash2", role="admin", is_active=True)
        self.db.add_all([self.user1, self.user2])

        # Seed Customers
        self.cust1 = Customer(id=1, external_id="cust_1", name="Alice", email="alice@test.io", country_code="IN")
        self.cust2 = Customer(id=2, external_id="cust_2", name="Bob", email="bob@test.io", country_code="IN")
        self.db.add_all([self.cust1, self.cust2])

        self.db.commit()

        self.token_m1 = create_access_token({"sub": "1", "merchant_id": 1, "role": "admin"})
        self.token_m2 = create_access_token({"sub": "2", "merchant_id": 2, "role": "admin"})
        self.auth_m1 = {"Authorization": f"Bearer {self.token_m1}"}
        self.auth_m2 = {"Authorization": f"Bearer {self.token_m2}"}

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        app.dependency_overrides.clear()

    def test_01_webhook_processing_failure_dlq_creates_recovery_case(self):
        """1. Webhook processing failure in DLQ triggers payment-state mismatch recovery case."""
        # Setup: transaction created locally but webhook failed repeatedly and went to DLQ
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_dlq_001",
            order_id="order_dlq_001",
            amount=Decimal("150000.00"),
            currency="INR",
            status="failed",
        )
        we = WebhookEvent(
            event_id="evt_dlq_001",
            event_type="payment.captured",
            payload=json.dumps({
                "entity": "event",
                "event": "payment.captured",
                "payload": {"payment": {"entity": {"id": "pay_dlq_001", "amount": 15000000, "status": "captured"}}},
            }),
            status="dead_letter",
        )
        self.db.add_all([tx, we])
        self.db.commit()

        mock_rzp = MagicMock(spec=RazorpayService)
        mock_rzp.payment_entity.return_value = {"id": "pay_dlq_001"}
        mock_rzp.fetch_payment.return_value = {"id": "pay_dlq_001", "status": "captured", "amount": 15000000}

        service = WebhookRecoveryService(rzp_service=mock_rzp)
        case = service.handle_dlq_event("evt_dlq_001", self.db)

        self.assertIsNotNone(case)
        self.assertEqual(case.exception_type, "webhook_payment_state_exception")
        self.assertEqual(case.amount_at_risk, Decimal("150000.00"))
        self.assertEqual(case.priority, "HIGH")
        self.assertEqual(case.status, "action_required")
        self.assertEqual(case.next_best_action, "SYNCHRONIZE_PAYMENT_STATE")

    def test_02_provider_local_payment_state_mismatch_creates_recovery_case(self):
        """2. Provider captured vs local action_required creates RecoveryCase."""
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_mismatch_002",
            order_id="order_mismatch_002",
            amount=Decimal("250000.00"),
            currency="INR",
            status="action_required",
        )
        self.db.add(tx)
        self.db.commit()

        mock_rzp = MagicMock(spec=RazorpayService)
        mock_rzp.fetch_payment.return_value = {"id": "pay_mismatch_002", "status": "captured", "amount": 25000000}

        service = WebhookRecoveryService(rzp_service=mock_rzp)
        case = service.detect_payment_mismatch(tx.id, merchant_id=1, db=self.db)

        self.assertIsNotNone(case)
        self.assertEqual(case.exception_type, "webhook_payment_state_exception")
        self.assertEqual(case.amount_at_risk, Decimal("250000.00"))
        self.assertEqual(case.stage, "payment_state_mismatch")

    def test_03_provider_local_state_agrees_no_recovery_case(self):
        """3. When provider state and local state agree, no RecoveryCase is created."""
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_agree_003",
            order_id="order_agree_003",
            amount=Decimal("5000.00"),
            currency="INR",
            status="captured",
        )
        self.db.add(tx)
        self.db.commit()

        mock_rzp = MagicMock(spec=RazorpayService)
        mock_rzp.fetch_payment.return_value = {"id": "pay_agree_003", "status": "captured", "amount": 500000}

        service = WebhookRecoveryService(rzp_service=mock_rzp)
        case = service.detect_payment_mismatch(tx.id, merchant_id=1, db=self.db)

        self.assertIsNone(case)
        case_count = self.db.scalar(select(RecoveryCase).where(RecoveryCase.transaction_id == tx.id))
        self.assertIsNone(case_count)

    def test_04_duplicate_detection_produces_one_recovery_case(self):
        """4. Repeated detection execution produces exactly 1 logical RecoveryCase."""
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_dup_004",
            amount=Decimal("75000.00"),
            currency="INR",
            status="failed",
        )
        self.db.add(tx)
        self.db.commit()

        mock_rzp = MagicMock(spec=RazorpayService)
        mock_rzp.fetch_payment.return_value = {"id": "pay_dup_004", "status": "captured"}

        service = WebhookRecoveryService(rzp_service=mock_rzp)
        case1 = service.detect_payment_mismatch(tx.id, merchant_id=1, db=self.db)
        case2 = service.detect_payment_mismatch(tx.id, merchant_id=1, db=self.db)

        self.assertEqual(case1.id, case2.id)
        all_cases = self.db.scalars(select(RecoveryCase).where(RecoveryCase.transaction_id == tx.id)).all()
        self.assertEqual(len(all_cases), 1)

    def test_05_existing_recovery_case_no_duplicate_case(self):
        """5. Updating an existing open recovery case does not spawn duplicate cases."""
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_exist_005",
            amount=Decimal("45000.00"),
            currency="INR",
            status="failed",
        )
        self.db.add(tx)
        self.db.flush()

        existing = RecoveryCase(
            merchant_id=1,
            transaction_id=tx.id,
            customer_id=1,
            exception_type="settlement_hold",
            status="action_required",
            stage="initial",
            amount_at_risk=Decimal("45000.00"),
        )
        self.db.add(existing)
        self.db.commit()

        mock_rzp = MagicMock(spec=RazorpayService)
        mock_rzp.fetch_payment.return_value = {"id": "pay_exist_005", "status": "captured"}

        service = WebhookRecoveryService(rzp_service=mock_rzp)
        updated_case = service.detect_payment_mismatch(tx.id, merchant_id=1, db=self.db)

        self.assertEqual(updated_case.id, existing.id)
        self.assertEqual(updated_case.exception_type, "webhook_payment_state_exception")
        total_cases = self.db.scalars(select(RecoveryCase).where(RecoveryCase.transaction_id == tx.id)).all()
        self.assertEqual(len(total_cases), 1)

    def test_06_resync_succeeds_marks_case_recovered(self):
        """6. Payment resync verifies provider state, updates Transaction, marks case recovered."""
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_sync_006",
            amount=Decimal("80000.00"),
            currency="INR",
            status="failed",
        )
        self.db.add(tx)
        self.db.flush()

        case = RecoveryCase(
            merchant_id=1,
            transaction_id=tx.id,
            customer_id=1,
            exception_type="webhook_payment_state_exception",
            status="action_required",
            stage="payment_state_mismatch",
            amount_at_risk=Decimal("80000.00"),
            next_best_action="SYNCHRONIZE_PAYMENT_STATE",
        )
        self.db.add(case)
        self.db.commit()

        mock_rzp = MagicMock(spec=RazorpayService)
        mock_rzp.fetch_payment.return_value = {"id": "pay_sync_006", "status": "captured"}

        service = WebhookRecoveryService(rzp_service=mock_rzp)
        res = service.resync_payment_state(tx.id, merchant_id=1, db=self.db)

        self.assertEqual(res["status"], "recovered")
        self.assertEqual(res["provider_status"], "captured")
        self.assertEqual(res["local_status"], "captured")

        self.db.refresh(tx)
        self.db.refresh(case)
        self.assertEqual(tx.status, "captured")
        self.assertEqual(case.status, "recovered")
        self.assertEqual(case.stage, "resolved")
        self.assertEqual(case.amount_at_risk, Decimal("0.00"))
        self.assertEqual(case.next_best_action, "PAYMENT_STATE_SYNCHRONIZED")

    def test_07_resync_fails_remains_unresolved(self):
        """7. Provider API failure during resync leaves case unresolved."""
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_fail_007",
            amount=Decimal("50000.00"),
            currency="INR",
            status="failed",
        )
        self.db.add(tx)
        self.db.flush()

        case = RecoveryCase(
            merchant_id=1,
            transaction_id=tx.id,
            customer_id=1,
            exception_type="webhook_payment_state_exception",
            status="action_required",
            stage="payment_state_mismatch",
            amount_at_risk=Decimal("50000.00"),
        )
        self.db.add(case)
        self.db.commit()

        mock_rzp = MagicMock(spec=RazorpayService)
        mock_rzp.fetch_payment.side_effect = HTTPException(status_code=503, detail="Razorpay unavailable")

        service = WebhookRecoveryService(rzp_service=mock_rzp)
        res = service.resync_payment_state(tx.id, merchant_id=1, db=self.db)

        self.assertEqual(res["status"], "unresolved")
        self.db.refresh(case)
        self.assertEqual(case.status, "action_required")
        self.assertEqual(case.amount_at_risk, Decimal("50000.00"))

    def test_08_cross_merchant_access_rejected(self):
        """8. Merchant 2 cannot resync or detect Merchant 1's transaction (HTTP 403 / IDOR defense)."""
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_m1_008",
            amount=Decimal("120000.00"),
            currency="INR",
            status="failed",
        )
        self.db.add(tx)
        self.db.commit()

        # Merchant 2 attempts to sync Merchant 1's transaction
        resp = self.client.post(f"/api/webhooks/recovery/{tx.id}/sync", headers=self.auth_m2)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("denied", resp.json()["detail"].lower())

    def test_09_financial_decimal_calculations(self):
        """9. Decimal precision verified for fractional currencies with zero float casting."""
        amount = Decimal("123456.78")
        tx = Transaction(
            merchant_id=1,
            customer_id=1,
            external_id="pay_dec_009",
            amount=amount,
            currency="INR",
            status="failed",
        )
        self.db.add(tx)
        self.db.commit()

        mock_rzp = MagicMock(spec=RazorpayService)
        mock_rzp.fetch_payment.return_value = {"id": "pay_dec_009", "status": "captured"}

        service = WebhookRecoveryService(rzp_service=mock_rzp)
        case = service.detect_payment_mismatch(tx.id, merchant_id=1, db=self.db)

        self.assertIsInstance(case.amount_at_risk, Decimal)
        self.assertEqual(case.amount_at_risk, Decimal("123456.78"))

    def test_10_existing_exception_types_remain_untouched(self):
        """10. Existing exception types maintain exact behavior in unified ExceptionRouter."""
        from app.intelligence.exception_router import ExceptionRouter

        router = ExceptionRouter()
        now = datetime.now(UTC)

        # Test chargeback_dispute
        case_disp = RecoveryCase(
            id=101,
            merchant_id=1,
            exception_type="chargeback_dispute",
            status="action_required",
            amount_at_risk=Decimal("50000.00"),
            created_at=now,
            updated_at=now,
        )
        read_disp = router.normalize_case(case_disp)
        self.assertEqual(read_disp.exception_type, "chargeback_dispute")
        self.assertEqual(read_disp.status, "action_required")

        # Test settlement_failure
        case_setl = RecoveryCase(
            id=102,
            merchant_id=1,
            exception_type="settlement_failure",
            status="open",
            amount_at_risk=Decimal("75000.00"),
            created_at=now,
            updated_at=now,
        )
        read_setl = router.normalize_case(case_setl)
        self.assertEqual(read_setl.exception_type, "settlement_failure")

        # Test reconciliation_variance
        case_recon = RecoveryCase(
            id=103,
            merchant_id=1,
            exception_type="reconciliation_variance",
            status="open",
            amount_at_risk=Decimal("1200.00"),
            created_at=now,
            updated_at=now,
        )
        read_recon = router.normalize_case(case_recon)
        self.assertEqual(read_recon.exception_type, "reconciliation_variance")

        # Test new webhook_payment_state_exception
        case_wh = RecoveryCase(
            id=104,
            merchant_id=1,
            exception_type="webhook_payment_state_exception",
            status="action_required",
            amount_at_risk=Decimal("99000.00"),
            created_at=now,
            updated_at=now,
        )
        read_wh = router.normalize_case(case_wh)
        self.assertEqual(read_wh.exception_type, "webhook_payment_state_exception")
        self.assertEqual(read_wh.status, "action_required")
        self.assertEqual(read_wh.recommended_action, "SYNCHRONIZE_PAYMENT_STATE")


if __name__ == "__main__":
    unittest.main()
