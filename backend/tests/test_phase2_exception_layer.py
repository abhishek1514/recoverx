"""Comprehensive Phase 2 Test Suite: Real Revenue Exception Data Layer & Razorpay Webhook Expansion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
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
from app.models.customer import Customer
from app.models.dispute import Dispute
from app.models.merchant import Merchant
from app.models.reconciliation import ReconciliationRecord
from app.models.recovery_case import RecoveryCase
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.services.dispute_parser import parse_and_normalize_dispute
from app.services.razorpay_service import RazorpayService
from app.services.settlement_parser import parse_and_normalize_settlement
from app.workers.tasks import process_razorpay_webhook


class Phase2ExceptionLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_schema()
        cls.client = TestClient(app)
        cls.client.__enter__()

        cls.service = RazorpayService(settings=get_settings())

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
    # 1. Model & Integrity Tests
    # =========================================================================
    def test_01_dispute_model_creation_and_decimal_types(self) -> None:
        disp_id = f"disp_test_{uuid4().hex[:8]}"
        with SessionLocal() as db:
            dispute = Dispute(
                merchant_id=1,
                razorpay_dispute_id=disp_id,
                payment_id=f"pay_{uuid4().hex[:8]}",
                amount=Decimal("1250.75"),
                currency="INR",
                reason_code="fraudulent",
                status="open",
                phase="chargeback",
            )
            db.add(dispute)
            db.commit()
            db.refresh(dispute)

            self.assertEqual(dispute.amount, Decimal("1250.75"))
            self.assertIsInstance(dispute.amount, Decimal)
            self.assertEqual(dispute.status, "open")

    def test_02_settlement_model_creation_and_decimal_types(self) -> None:
        setl_id = f"setl_test_{uuid4().hex[:8]}"
        with SessionLocal() as db:
            settlement = Settlement(
                merchant_id=1,
                razorpay_settlement_id=setl_id,
                utr="UTR_TEST_9999",
                amount=Decimal("50000.00"),
                fees=Decimal("1000.00"),
                tax=Decimal("180.00"),
                currency="INR",
                status="processed",
            )
            db.add(settlement)
            db.commit()
            db.refresh(settlement)

            self.assertEqual(settlement.amount, Decimal("50000.00"))
            self.assertEqual(settlement.fees, Decimal("1000.00"))
            self.assertEqual(settlement.tax, Decimal("180.00"))
            self.assertIsInstance(settlement.fees, Decimal)

    def test_03_reconciliation_record_model_creation(self) -> None:
        with SessionLocal() as db:
            recon = ReconciliationRecord(
                merchant_id=1,
                expected_amount=Decimal("10000.00"),
                settled_amount=Decimal("9764.00"),
                fee_amount=Decimal("200.00"),
                tax_amount=Decimal("36.00"),
                discrepancy_amount=Decimal("0.00"),
                discrepancy_type="none",
                status="reconciled",
            )
            db.add(recon)
            db.commit()
            db.refresh(recon)

            self.assertEqual(recon.settled_amount, Decimal("9764.00"))
            self.assertEqual(recon.status, "reconciled")

    def test_04_recovery_case_extension_with_exception_types(self) -> None:
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            tx = Transaction(
                merchant_id=1,
                external_id=f"pay_disp_tx_{tag}",
                amount=Decimal("5000.00"),
                currency="INR",
                status="captured",
            )
            db.add(tx)
            db.flush()

            disp = Dispute(
                merchant_id=1,
                transaction_id=tx.id,
                razorpay_dispute_id=f"disp_ext_{tag}",
                amount=Decimal("5000.00"),
                currency="INR",
                status="action_required",
            )
            db.add(disp)
            db.flush()

            case = RecoveryCase(
                merchant_id=1,
                transaction_id=tx.id,
                exception_type="chargeback_dispute",
                dispute_id=disp.id,
                status="action_required",
                stage="chargeback_dispute",
                amount_at_risk=Decimal("5000.00"),
                next_best_action="CONTEST_DISPUTE",
            )
            db.add(case)
            db.commit()
            db.refresh(case)

            self.assertEqual(case.exception_type, "chargeback_dispute")
            self.assertEqual(case.dispute_id, disp.id)
            self.assertEqual(case.amount_at_risk, Decimal("5000.00"))

    # =========================================================================
    # 2. Razorpay Dispute Webhook Ingestion Tests
    # =========================================================================
    def test_05_dispute_created_webhook_ingestion(self) -> None:
        tag = uuid4().hex[:8]
        now_ts = int(datetime.now(UTC).timestamp())
        payload = {
            "entity": "event",
            "account_id": "acc_test_01",
            "event": "payment.dispute.created",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_disp_wh_{tag}",
                        "amount": 250000,
                        "currency": "INR",
                        "status": "captured",
                    }
                },
                "dispute": {
                    "entity": {
                        "id": f"disp_wh_{tag}",
                        "payment_id": f"pay_disp_wh_{tag}",
                        "amount": 250000,
                        "currency": "INR",
                        "reason_code": "fraudulent",
                        "status": "open",
                        "phase": "chargeback",
                        "respond_by": now_ts + 86400 * 7,
                        "deducted_at": now_ts,
                        "created_at": now_ts,
                    }
                },
            },
            "created_at": now_ts,
        }
        body = json.dumps(payload).encode("utf-8")
        sig = self.service.create_test_signature(body)

        res = self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
        )
        self.assertEqual(res.status_code, 200)

        with SessionLocal() as db:
            disp = db.scalar(select(Dispute).where(Dispute.razorpay_dispute_id == f"disp_wh_{tag}"))
            self.assertIsNotNone(disp)
            self.assertEqual(disp.amount, Decimal("2500.00"))
            self.assertEqual(disp.status, "open")
            self.assertEqual(disp.reason_code, "fraudulent")

            case = db.scalar(select(RecoveryCase).where(RecoveryCase.dispute_id == disp.id))
            self.assertIsNotNone(case)
            self.assertEqual(case.exception_type, "chargeback_dispute")
            self.assertEqual(case.next_best_action, "CONTEST_DISPUTE")

    def test_06_dispute_won_updates_case_to_recovered(self) -> None:
        tag = uuid4().hex[:8]
        now_ts = int(datetime.now(UTC).timestamp())
        payload = {
            "entity": "event",
            "event": "payment.dispute.won",
            "payload": {
                "dispute": {
                    "entity": {
                        "id": f"disp_wh_{tag}",
                        "payment_id": f"pay_disp_wh_{tag}",
                        "amount": 100000,
                        "currency": "INR",
                        "status": "won",
                        "phase": "chargeback",
                    }
                }
            },
            "created_at": now_ts,
        }
        body = json.dumps(payload).encode("utf-8")
        sig = self.service.create_test_signature(body)

        res = self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
        )
        self.assertEqual(res.status_code, 200)

        with SessionLocal() as db:
            disp = db.scalar(select(Dispute).where(Dispute.razorpay_dispute_id == f"disp_wh_{tag}"))
            self.assertIsNotNone(disp)
            self.assertEqual(disp.status, "won")

            case = db.scalar(select(RecoveryCase).where(RecoveryCase.dispute_id == disp.id))
            self.assertIsNotNone(case)
            self.assertEqual(case.status, "recovered")
            self.assertEqual(case.recovery_probability, Decimal("1.00"))

    # =========================================================================
    # 3. Razorpay Settlement Webhook Ingestion Tests
    # =========================================================================
    def test_07_settlement_processed_webhook_ingestion(self) -> None:
        tag = uuid4().hex[:8]
        now_ts = int(datetime.now(UTC).timestamp())
        payload = {
            "entity": "event",
            "event": "settlement.processed",
            "payload": {
                "settlement": {
                    "entity": {
                        "id": f"setl_wh_{tag}",
                        "amount": 10000000,
                        "fees": 20000,
                        "tax": 3600,
                        "currency": "INR",
                        "utr": f"UTR_SETL_WH_{tag}",
                        "status": "processed",
                        "settled_at": now_ts,
                        "created_at": now_ts,
                    }
                }
            },
            "created_at": now_ts,
        }
        body = json.dumps(payload).encode("utf-8")
        sig = self.service.create_test_signature(body)

        res = self.client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
        )
        self.assertEqual(res.status_code, 200)

        with SessionLocal() as db:
            setl = db.scalar(select(Settlement).where(Settlement.razorpay_settlement_id == f"setl_wh_{tag}"))
            self.assertIsNotNone(setl)
            self.assertEqual(setl.amount, Decimal("100000.00"))
            self.assertEqual(setl.fees, Decimal("200.00"))
            self.assertEqual(setl.tax, Decimal("36.00"))
            self.assertEqual(setl.utr, f"UTR_SETL_WH_{tag}")
            self.assertEqual(setl.status, "processed")

    # =========================================================================
    # 4. Out-of-Order State Precedence Tests
    # =========================================================================
    def test_08_out_of_order_dispute_status_precedence(self) -> None:
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            disp = Dispute(
                merchant_id=1,
                razorpay_dispute_id=f"disp_ooo_{tag}",
                amount=Decimal("3000.00"),
                currency="INR",
                status="won",
            )
            db.add(disp)
            db.commit()

            late_payload = {
                "dispute": {
                    "entity": {
                        "id": f"disp_ooo_{tag}",
                        "amount": 300000,
                        "currency": "INR",
                        "status": "under_review",
                    }
                }
            }
            # Simulate out-of-order late webhook arrival
            updated = parse_and_normalize_dispute(
                payload=late_payload,
                event_type="payment.dispute.under_review",
                event_id=f"evt_late_{tag}",
                db=db,
                merchant_id=1,
            )
            # Must remain 'won' and not regress to 'under_review'
            self.assertEqual(updated.status, "won")

    def test_09_out_of_order_settlement_status_precedence(self) -> None:
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            setl = Settlement(
                merchant_id=1,
                razorpay_settlement_id=f"setl_ooo_{tag}",
                amount=Decimal("5000.00"),
                currency="INR",
                status="processed",
            )
            db.add(setl)
            db.commit()

            late_payload = {
                "settlement": {
                    "entity": {
                        "id": f"setl_ooo_{tag}",
                        "amount": 500000,
                        "currency": "INR",
                        "status": "pending",
                    }
                }
            }
            updated = parse_and_normalize_settlement(
                payload=late_payload,
                event_type="settlement.processed",
                event_id=f"evt_late_setl_{tag}",
                db=db,
                merchant_id=1,
            )
            # Must remain 'processed'
            self.assertEqual(updated.status, "processed")

    # =========================================================================
    # 5. Multi-Tenant Isolation Tests
    # =========================================================================
    def test_10_cross_merchant_dispute_access_forbidden(self) -> None:
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            disp_m1 = Dispute(
                merchant_id=1,
                razorpay_dispute_id=f"disp_m1_{tag}",
                amount=Decimal("2000.00"),
                currency="INR",
                status="open",
            )
            db.add(disp_m1)
            db.commit()
            db.refresh(disp_m1)
            m1_dispute_id = disp_m1.id

        # Merchant 2 attempting to access Merchant 1's dispute
        res = self.client.get(
            f"/api/disputes/{m1_dispute_id}",
            headers={"Authorization": f"Bearer {self.token_m2}"},
        )
        self.assertEqual(res.status_code, 403)

    def test_11_cross_merchant_settlement_access_forbidden(self) -> None:
        tag = uuid4().hex[:8]
        with SessionLocal() as db:
            setl_m1 = Settlement(
                merchant_id=1,
                razorpay_settlement_id=f"setl_m1_{tag}",
                amount=Decimal("15000.00"),
                currency="INR",
                status="processed",
            )
            db.add(setl_m1)
            db.commit()
            db.refresh(setl_m1)
            m1_settlement_id = setl_m1.id

        # Merchant 2 attempting to access Merchant 1's settlement
        res = self.client.get(
            f"/api/settlements/{m1_settlement_id}",
            headers={"Authorization": f"Bearer {self.token_m2}"},
        )
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # 6. Razorpay API Client Foundation Tests
    # =========================================================================
    @patch("app.services.razorpay_service.httpx.Client")
    def test_12_get_dispute_api_call(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "disp_api_001",
            "entity": "dispute",
            "amount": 50000,
            "currency": "INR",
            "status": "open",
        }
        mock_client.get.return_value = mock_resp

        result = self.service.get_dispute("disp_api_001")
        self.assertEqual(result["id"], "disp_api_001")
        mock_client.get.assert_called_once()

    @patch("app.services.razorpay_service.httpx.Client")
    def test_13_contest_dispute_api_call(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "disp_api_001", "status": "under_review"}
        mock_client.patch.return_value = mock_resp

        result = self.service.contest_dispute(
            dispute_id="disp_api_001",
            summary="Product delivered with tracking number TRK123456",
            documents=["doc_12345"],
        )
        self.assertEqual(result["status"], "under_review")
        mock_client.patch.assert_called_once()

    @patch("app.services.razorpay_service.httpx.Client")
    def test_14_get_settlements_api_call(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "entity": "collection",
            "count": 1,
            "items": [{"id": "setl_api_001", "amount": 1000000, "status": "processed"}],
        }
        mock_client.get.return_value = mock_resp

        items = self.service.get_settlements(count=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "setl_api_001")


if __name__ == "__main__":
    unittest.main()
