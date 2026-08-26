"""Comprehensive Test Suite for RecoverX Phase 4: Production Settlement Exception Recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.database.connection import ensure_schema
from app.database.session import SessionLocal
from app.main import app
from app.models.audit_log import AuditLog
from app.models.merchant import Merchant
from app.models.reconciliation import ReconciliationRecord
from app.models.recovery_case import RecoveryCase
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.models.user import User
from app.services.razorpay_service import RazorpayService
from app.services.settlement_sync_service import (
    SettlementSyncService,
    determine_settlement_failure_action,
)


class Phase4SettlementWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_schema()
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.service = RazorpayService(settings=get_settings())
        cls.sync_service = SettlementSyncService(rzp_service=cls.service)

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
    # 1. Synchronization, Pagination & Idempotent Upsert
    # =========================================================================
    @patch("app.services.razorpay_service.httpx.Client")
    def test_01_settlement_api_synchronization_and_pagination(self, mock_client_cls: MagicMock) -> None:
        """1. Test synchronization handles pagination across multiple batches."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        # Batch 1 (2 items)
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = {
            "entity": "collection",
            "count": 2,
            "items": [
                {"id": "setl_page_01", "amount": 10000000, "status": "processed", "fees": 20000, "tax": 3600},
                {"id": "setl_page_02", "amount": 5000000, "status": "processed", "fees": 10000, "tax": 1800},
            ],
        }
        # Batch 2 (0 items -> terminates)
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {"entity": "collection", "count": 0, "items": []}

        mock_client.get.side_effect = [resp1, resp2]

        with SessionLocal() as db:
            result = self.sync_service.sync_settlements(merchant_id=1, db=db, batch_size=2)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["total_synced"], 2)

            # Verify persisted
            s1 = db.scalar(select(Settlement).where(Settlement.razorpay_settlement_id == "setl_page_01"))
            self.assertIsNotNone(s1)
            self.assertEqual(s1.amount, Decimal("100000.00"))

    @patch("app.services.razorpay_service.httpx.Client")
    def test_02_idempotent_duplicate_settlement_synchronization(self, mock_client_cls: MagicMock) -> None:
        """2. Test that running synchronization repeatedly does not duplicate records or cases."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tag = uuid4().hex[:8]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "entity": "collection",
            "count": 1,
            "items": [
                {
                    "id": f"setl_dup_{tag}",
                    "amount": 2500000,
                    "currency": "INR",
                    "status": "failed",
                    "failure_reason": "Bank account IFSC code invalid",
                    "fees": 0,
                    "tax": 0,
                }
            ],
        }
        mock_client.get.return_value = resp

        with SessionLocal() as db:
            # First sync
            res1 = self.sync_service.sync_settlements(merchant_id=1, db=db)
            self.assertEqual(res1["total_synced"], 1)

            # Second sync (same item)
            res2 = self.sync_service.sync_settlements(merchant_id=1, db=db)
            self.assertEqual(res2["total_synced"], 1)

            # Assert exactly 1 settlement record exists
            settlements = list(
                db.scalars(
                    select(Settlement).where(
                        Settlement.merchant_id == 1,
                        Settlement.razorpay_settlement_id == f"setl_dup_{tag}",
                    )
                ).all()
            )
            self.assertEqual(len(settlements), 1)

            # Assert exactly 1 active recovery case exists
            cases = list(
                db.scalars(
                    select(RecoveryCase).where(
                        RecoveryCase.merchant_id == 1,
                        RecoveryCase.settlement_id == settlements[0].id,
                    )
                ).all()
            )
            self.assertEqual(len(cases), 1)

    # =========================================================================
    # 2. Settlement Failure & Exception Case Creation
    # =========================================================================
    @patch("app.services.razorpay_service.httpx.Client")
    def test_03_settlement_failure_creates_recovery_case_with_exact_risk(self, mock_client_cls: MagicMock) -> None:
        """3. Test that settlement status='failed' creates a RecoveryCase with exact amount at risk."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tag = uuid4().hex[:8]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "entity": "collection",
            "count": 1,
            "items": [
                {
                    "id": f"setl_fail_{tag}",
                    "amount": 100000000,  # ₹10,00,000 INR
                    "currency": "INR",
                    "status": "failed",
                    "failure_reason": "Beneficiary bank rejected transaction (invalid IFSC code).",
                    "fees": 0,
                    "tax": 0,
                }
            ],
        }
        mock_client.get.return_value = resp

        with SessionLocal() as db:
            result = self.sync_service.sync_settlements(merchant_id=1, db=db)
            self.assertEqual(result["exceptions_detected"], 1)

            s = db.scalar(select(Settlement).where(Settlement.razorpay_settlement_id == f"setl_fail_{tag}"))
            self.assertIsNotNone(s)
            self.assertEqual(s.amount, Decimal("1000000.00"))
            self.assertEqual(s.status, "failed")

            case = db.scalar(select(RecoveryCase).where(RecoveryCase.settlement_id == s.id))
            self.assertIsNotNone(case)
            self.assertEqual(case.exception_type, "settlement_failure")
            self.assertEqual(case.amount_at_risk, Decimal("1000000.00"))
            self.assertEqual(case.next_best_action, "VERIFY_BANK_ACCOUNT")

    # =========================================================================
    # 3. Deterministic Action Mapping & Reason Handling
    # =========================================================================
    def test_04_failure_reason_deterministic_action_mapping(self) -> None:
        """4. Test mapping of failure reasons to deterministic recommendations."""
        # Bank error -> VERIFY_BANK_ACCOUNT
        act1 = determine_settlement_failure_action("Invalid beneficiary bank account number")
        self.assertEqual(act1, "VERIFY_BANK_ACCOUNT")

        # KYC error -> COMPLETE_REQUIRED_INFORMATION
        act2 = determine_settlement_failure_action("Merchant KYC compliance documentation missing")
        self.assertEqual(act2, "COMPLETE_REQUIRED_INFORMATION")

        # Generic / Unknown -> CONTACT_RAZORPAY_SUPPORT
        act3 = determine_settlement_failure_action("Internal banking network gateway timeout")
        self.assertEqual(act3, "CONTACT_RAZORPAY_SUPPORT")

        act4 = determine_settlement_failure_action(None)
        self.assertEqual(act4, "CONTACT_RAZORPAY_SUPPORT")

    # =========================================================================
    # 4. Unknown Status Handling (Never Map to False Failure)
    # =========================================================================
    @patch("app.services.razorpay_service.httpx.Client")
    def test_05_unknown_status_normalized_safely(self, mock_client_cls: MagicMock) -> None:
        """5. Test that unknown provider status becomes 'unknown' rather than false failed."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tag = uuid4().hex[:8]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "entity": "collection",
            "count": 1,
            "items": [
                {
                    "id": f"setl_unk_{tag}",
                    "amount": 250000,
                    "currency": "INR",
                    "status": "awaiting_nodal_clearance",  # Non-standard status
                    "fees": 0,
                    "tax": 0,
                }
            ],
        }
        mock_client.get.return_value = resp

        with SessionLocal() as db:
            self.sync_service.sync_settlements(merchant_id=1, db=db)
            s = db.scalar(select(Settlement).where(Settlement.razorpay_settlement_id == f"setl_unk_{tag}"))
            self.assertIsNotNone(s)
            self.assertEqual(s.status, "unknown")

    # =========================================================================
    # 5. Out-of-Order State Precedence
    # =========================================================================
    @patch("app.services.razorpay_service.httpx.Client")
    def test_06_state_machine_precedence_preserves_processed_state(self, mock_client_cls: MagicMock) -> None:
        """6. Test that a terminal 'processed' status cannot be regressed by out-of-order 'created' status."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            s = Settlement(
                merchant_id=1,
                razorpay_settlement_id=f"setl_prec_{tag}",
                amount=Decimal("75000.00"),
                currency="INR",
                status="processed",
            )
            db.add(s)
            db.commit()

        # Incoming stale status 'created'
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "entity": "collection",
            "count": 1,
            "items": [
                {
                    "id": f"setl_prec_{tag}",
                    "amount": 7500000,
                    "currency": "INR",
                    "status": "created",
                    "fees": 0,
                    "tax": 0,
                }
            ],
        }
        mock_client.get.return_value = resp

        with SessionLocal() as db:
            self.sync_service.sync_settlements(merchant_id=1, db=db)
            updated_s = db.scalar(select(Settlement).where(Settlement.razorpay_settlement_id == f"setl_prec_{tag}"))
            self.assertEqual(updated_s.status, "processed")

    # =========================================================================
    # 6. Settlement Resolution Cycle (Only Processed Marks Recovered)
    # =========================================================================
    @patch("app.services.razorpay_service.httpx.Client")
    def test_07_recheck_settlement_resolves_only_when_processed(self, mock_client_cls: MagicMock) -> None:
        """7. Test that resyncing settlement resolves case only when Razorpay returns status='processed'."""
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            tx = Transaction(
                merchant_id=1,
                external_id=f"setl_tx_init_{tag}",
                amount=Decimal("50000.00"),
                currency="INR",
                status="action_required",
            )
            db.add(tx)
            db.flush()

            s = Settlement(
                merchant_id=1,
                razorpay_settlement_id=f"setl_res_{tag}",
                amount=Decimal("50000.00"),
                currency="INR",
                status="failed",
                failure_reason="Bank account error",
            )
            db.add(s)
            db.flush()
            case = RecoveryCase(
                merchant_id=1,
                transaction_id=tx.id,
                settlement_id=s.id,
                exception_type="settlement_failure",
                status="action_required",
                amount_at_risk=Decimal("50000.00"),
            )
            db.add(case)
            db.commit()
            settlement_id = s.id

        # 1. Simulate re-sync when Razorpay still reports failed
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_resp_fail = MagicMock()
        mock_resp_fail.status_code = 200
        mock_resp_fail.json.return_value = {
            "id": f"setl_res_{tag}",
            "amount": 5000000,
            "currency": "INR",
            "status": "failed",
            "failure_reason": "Bank account error",
        }
        mock_client.get.return_value = mock_resp_fail

        res1 = self.client.post(
            f"/api/settlements/{settlement_id}/sync",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res1.status_code, 200)
        with SessionLocal() as db:
            c1 = db.scalar(select(RecoveryCase).where(RecoveryCase.settlement_id == settlement_id))
            self.assertEqual(c1.status, "action_required")  # Remains unresolved

        # 2. Simulate re-sync when Razorpay confirms processed
        mock_resp_proc = MagicMock()
        mock_resp_proc.status_code = 200
        mock_resp_proc.json.return_value = {
            "id": f"setl_res_{tag}",
            "amount": 5000000,
            "currency": "INR",
            "status": "processed",
            "utr": "UTR_SUCCESS_12345",
            "fees": 10000,
            "tax": 1800,
        }
        mock_client.get.return_value = mock_resp_proc

        res2 = self.client.post(
            f"/api/settlements/{settlement_id}/sync",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res2.status_code, 200)
        with SessionLocal() as db:
            c2 = db.scalar(select(RecoveryCase).where(RecoveryCase.settlement_id == settlement_id))
            self.assertEqual(c2.status, "recovered")
            self.assertEqual(c2.recovery_probability, Decimal("1.00"))

    # =========================================================================
    # 7. Reconciliation: Explained vs Unexplained Variances
    # =========================================================================
    @patch("app.services.razorpay_service.httpx.Client")
    def test_08_reconciliation_explained_variance_does_not_create_case(self, mock_client_cls: MagicMock) -> None:
        """8. Test that fully explained variance (fees + tax + refund) does not create exception case."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Expected: ₹10,000 | Settled: ₹9,764 | Fee: ₹200 | Tax: ₹36 -> Unexplained: 0
        mock_resp.json.return_value = {
            "items": [
                {
                    "amount": 1000000,
                    "settled_amount": 976400,
                    "fee": 20000,
                    "tax": 3600,
                    "refund": 0,
                    "adjustment": 0,
                    "type": "standard_recon",
                }
            ]
        }
        mock_client.get.return_value = mock_resp

        with SessionLocal() as db:
            records = self.sync_service.sync_reconciliation_records(2026, 8, 26, merchant_id=1, db=db)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, "explained")
            self.assertEqual(records[0].discrepancy_amount, Decimal("0.00"))

            # No recovery case generated
            case = db.scalar(select(RecoveryCase).where(RecoveryCase.reconciliation_record_id == records[0].id))
            self.assertIsNone(case)

    @patch("app.services.razorpay_service.httpx.Client")
    def test_09_reconciliation_unexplained_variance_creates_case(self, mock_client_cls: MagicMock) -> None:
        """9. Test that unexplained variance above threshold creates a RecoveryCase."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Expected: ₹10,00,000 | Settled: ₹9,50,000 | Fee: ₹20,000 | Tax: ₹5,000 | Refund: ₹10,000 -> Unexplained: ₹15,000
        mock_resp.json.return_value = {
            "items": [
                {
                    "amount": 100000000,
                    "settled_amount": 95000000,
                    "fee": 2000000,
                    "tax": 500000,
                    "refund": 1000000,
                    "adjustment": 0,
                    "type": "discrepant_recon",
                }
            ]
        }
        mock_client.get.return_value = mock_resp

        with SessionLocal() as db:
            records = self.sync_service.sync_reconciliation_records(2026, 8, 26, merchant_id=1, db=db)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, "unexplained")
            self.assertEqual(records[0].discrepancy_amount, Decimal("15000.00"))

            case = db.scalar(select(RecoveryCase).where(RecoveryCase.reconciliation_record_id == records[0].id))
            self.assertIsNotNone(case)
            self.assertEqual(case.exception_type, "reconciliation_variance")
            self.assertEqual(case.amount_at_risk, Decimal("15000.00"))

    # =========================================================================
    # 8. Endpoints, Metrics & Multi-Tenant Isolation
    # =========================================================================
    def test_10_settlement_exceptions_and_metrics_endpoints(self) -> None:
        """10. Test /api/settlements/exceptions and /api/settlements/metrics."""
        res_exc = self.client.get(
            "/api/settlements/exceptions",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res_exc.status_code, 200)

        res_met = self.client.get(
            "/api/settlements/metrics",
            headers={"Authorization": f"Bearer {self.token_m1}"},
        )
        self.assertEqual(res_met.status_code, 200)
        met = res_met.json()
        self.assertIn("total_settled_amount", met)
        self.assertIn("amount_failed", met)
        self.assertIn("currency", met)

    def test_11_cross_merchant_settlement_sync_access_forbidden(self) -> None:
        """11. Test that Merchant 2 cannot trigger sync on Merchant 1's settlement."""
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            s_m1 = Settlement(
                merchant_id=1,
                razorpay_settlement_id=f"setl_iso_{tag}",
                amount=Decimal("20000.00"),
                currency="INR",
                status="failed",
            )
            db.add(s_m1)
            db.commit()
            db.refresh(s_m1)
            m1_id = s_m1.id

        res = self.client.post(
            f"/api/settlements/{m1_id}/sync",
            headers={"Authorization": f"Bearer {self.token_m2}"},
        )
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()

