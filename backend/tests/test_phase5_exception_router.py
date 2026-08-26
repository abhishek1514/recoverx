"""Comprehensive Test Suite for RecoverX Phase 5: Unified Revenue Exception Router."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.database.connection import ensure_schema
from app.database.session import SessionLocal
from app.intelligence.exception_router import ExceptionRouter
from app.main import app
from app.models.dispute import Dispute
from app.models.merchant import Merchant
from app.models.reconciliation import ReconciliationRecord
from app.models.recovery_case import RecoveryCase
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.models.user import User


class Phase5ExceptionRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_schema()
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.router_engine = ExceptionRouter(settings=get_settings())

        with SessionLocal() as db:
            m2 = db.scalar(select(Merchant).where(Merchant.id == 2))
            if m2 is None:
                m2 = Merchant(id=2, name="Secondary Merchant", country_code="US", currency="USD", is_active=True)
                db.add(m2)
                db.flush()

            u2 = db.scalar(select(User).where(User.id == 2))
            if u2 is None:
                u2 = User(
                    id=2,
                    merchant_id=2,
                    email="admin2@merchant.com",
                    hashed_password=hash_password("admin123456"),
                    full_name="Merchant 2 Admin",
                    role="merchant_admin",
                    is_active=True,
                )
                db.add(u2)
            db.commit()

        cls.token_m1 = create_access_token(data={"sub": "1", "merchant_id": 1})
        cls.token_m2 = create_access_token(data={"sub": "2", "merchant_id": 2})

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    # =========================================================================
    # 1. Unified Normalization & Exact Financial Integrity
    # =========================================================================
    def test_01_dispute_normalized_as_unified_exception(self) -> None:
        """1. Test that a dispute appears as a unified chargeback_dispute exception."""
        tag = uuid4().hex[:8]
        now = datetime.now(UTC)
        with SessionLocal() as db:
            tx = Transaction(
                merchant_id=1,
                external_id=f"tx_disp_p5_{tag}",
                amount=Decimal("50000.00"),
                currency="INR",
                status="action_required",
            )
            db.add(tx)
            db.flush()

            disp = Dispute(
                merchant_id=1,
                razorpay_dispute_id=f"disp_p5_{tag}",
                amount=Decimal("50000.00"),
                currency="INR",
                reason_code="fraudulent",
                status="open",
                respond_by=now + timedelta(hours=18),
                deadline_status="deadline_critical",
            )
            db.add(disp)
            db.flush()

            case = RecoveryCase(
                merchant_id=1,
                transaction_id=tx.id,
                dispute_id=disp.id,
                exception_type="chargeback_dispute",
                status="action_required",
                amount_at_risk=Decimal("50000.00"),
            )
            db.add(case)
            db.commit()
            case_id = case.id

        res = self.client.get(
            f"/api/exceptions/{case_id}",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["exception_type"], "chargeback_dispute")
        self.assertEqual(Decimal(str(data["amount_at_risk"])), Decimal("50000.00"))
        self.assertEqual(data["priority"], "CRITICAL")  # Critical because < 24h
        self.assertEqual(data["status"], "action_required")
        self.assertEqual(data["provider_status"], "open")
        self.assertEqual(data["recommended_action"], "COLLECT_EVIDENCE")

    def test_02_settlement_failure_normalized_as_unified_exception(self) -> None:
        """2. Test that a settlement failure appears with bank verification action."""
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            tx = Transaction(
                merchant_id=1,
                external_id=f"tx_setl_p5_{tag}",
                amount=Decimal("1200000.00"),
                currency="INR",
                status="action_required",
            )
            db.add(tx)
            db.flush()

            s = Settlement(
                merchant_id=1,
                razorpay_settlement_id=f"setl_p5_{tag}",
                amount=Decimal("1200000.00"),  # ₹12,00,000 INR
                currency="INR",
                status="failed",
                failure_reason="Beneficiary bank account number invalid.",
            )
            db.add(s)
            db.flush()

            case = RecoveryCase(
                merchant_id=1,
                transaction_id=tx.id,
                settlement_id=s.id,
                exception_type="settlement_failure",
                status="action_required",
                amount_at_risk=Decimal("1200000.00"),
            )
            db.add(case)
            db.commit()
            case_id = case.id

        res = self.client.get(
            f"/api/exceptions/{case_id}",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["exception_type"], "settlement_failure")
        self.assertEqual(Decimal(str(data["amount_at_risk"])), Decimal("1200000.00"))
        self.assertEqual(data["priority"], "CRITICAL")  # Critical because >= ₹10L
        self.assertEqual(data["recommended_action"], "VERIFY_BANK_DETAILS")

    def test_03_reconciliation_variance_normalized_as_unified_exception(self) -> None:
        """3. Test that an unexplained reconciliation variance appears as unified exception."""
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            tx = Transaction(
                merchant_id=1,
                external_id=f"tx_recon_p5_{tag}",
                amount=Decimal("2640.00"),
                currency="INR",
                status="action_required",
            )
            db.add(tx)
            db.flush()

            recon = ReconciliationRecord(
                merchant_id=1,
                expected_amount=Decimal("100000.00"),
                settled_amount=Decimal("95000.00"),
                fee_amount=Decimal("2000.00"),
                tax_amount=Decimal("360.00"),
                refund_amount=Decimal("0.00"),
                adjustment_amount=Decimal("0.00"),
                discrepancy_amount=Decimal("2640.00"),
                discrepancy_type="standard_settlement",
                status="unexplained",
            )
            db.add(recon)
            db.flush()

            case = RecoveryCase(
                merchant_id=1,
                transaction_id=tx.id,
                reconciliation_record_id=recon.id,
                exception_type="reconciliation_variance",
                status="action_required",
                amount_at_risk=Decimal("2640.00"),
            )
            db.add(case)
            db.commit()
            case_id = case.id

        res = self.client.get(
            f"/api/exceptions/{case_id}",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["exception_type"], "reconciliation_variance")
        self.assertEqual(Decimal(str(data["amount_at_risk"])), Decimal("2640.00"))
        self.assertEqual(data["recommended_action"], "INVESTIGATE_VARIANCE")

    # =========================================================================
    # 2. Unified Metrics & No Double-Counting
    # =========================================================================
    def test_04_unified_metrics_calculation_and_no_double_counting(self) -> None:
        """4. Test that GET /api/exceptions/metrics returns exact totals without double-counting."""
        res = self.client.get(
            "/api/exceptions/metrics",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res.status_code, 200)
        metrics = res.json()

        self.assertIn("total_exceptions", metrics)
        self.assertIn("total_amount_at_risk", metrics)
        self.assertIn("critical_count", metrics)
        self.assertIn("recovery_rate", metrics)
        self.assertTrue(Decimal(str(metrics["total_amount_at_risk"])) > Decimal("0.00"))

    # =========================================================================
    # 3. Filtering Capabilities
    # =========================================================================
    def test_05_list_exceptions_with_filters(self) -> None:
        """5. Test listing exceptions with priority and type filters."""
        # Filter by priority=CRITICAL
        res_crit = self.client.get(
            "/api/exceptions?priority=CRITICAL",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res_crit.status_code, 200)
        items_crit = res_crit.json()
        for item in items_crit:
            self.assertEqual(item["priority"], "CRITICAL")

        # Filter by type=chargeback_dispute
        res_type = self.client.get(
            "/api/exceptions?type=chargeback_dispute",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res_type.status_code, 200)
        items_type = res_type.json()
        for item in items_type:
            self.assertEqual(item["exception_type"], "chargeback_dispute")

    # =========================================================================
    # 4. Multi-Tenant Isolation
    # =========================================================================
    def test_06_cross_merchant_exception_access_forbidden(self) -> None:
        """6. Test that Merchant 2 cannot view Merchant 1's exception details."""
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            tx = Transaction(
                merchant_id=1,
                external_id=f"tx_iso_p5_{tag}",
                amount=Decimal("15000.00"),
                currency="INR",
                status="action_required",
            )
            db.add(tx)
            db.flush()

            case_m1 = RecoveryCase(
                merchant_id=1,
                transaction_id=tx.id,
                exception_type="settlement_hold",
                status="action_required",
                amount_at_risk=Decimal("15000.00"),
            )
            db.add(case_m1)
            db.commit()
            db.refresh(case_m1)
            m1_id = case_m1.id

        res = self.client.get(
            f"/api/exceptions/{m1_id}",
            headers={"Authorization": f"Bearer {self.token_m2}"},
        )
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()

