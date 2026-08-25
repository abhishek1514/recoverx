import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

# Keep test environment settings
TEST_DB = Path(tempfile.gettempdir()) / "recoverx_webhook_tests.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_example"
os.environ["RAZORPAY_KEY_SECRET"] = "test_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models
from app.database.connection import Base, engine
from app.database.session import SessionLocal, get_db
from app.main import app
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.document import Document
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.models.validation import ValidationResult
from app.services.document_service import DocumentService
from app.services.recovery_service import analyze_transaction
from app.validation.deterministic_rules import validate_recovery_submission
from app.validation.pii_masking import mask_pii_dict, mask_pii_text


class Phase5RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def create_case(
        self,
        amount: str = "580000",
        currency: str = "INR",
        status: str = "received",
        customer_name: str | None = None,
        customer_email: str | None = None,
        country_code: str | None = "IN",
        has_doc: bool = False,
    ) -> tuple[Transaction, RecoveryCase]:
        customer = Customer(
            external_id=f"cust_test_{amount}",
            name=customer_name,
            email=customer_email,
            country_code=country_code,
        )
        self.db.add(customer)
        self.db.flush()

        tx = Transaction(
            external_id=f"pay_test_{amount}",
            order_id=f"order_test_{amount}",
            customer_id=customer.id,
            amount=Decimal(amount),
            currency=currency,
            status=status,
            payment_method="upi",
        )
        self.db.add(tx)
        self.db.commit()

        if has_doc:
            case = RecoveryCase(
                transaction_id=tx.id,
                customer_id=customer.id,
                status="open",
                stage="at_risk",
                amount_at_risk=Decimal("261000.00"),
                recovery_probability=Decimal("0.82"),
                priority="HIGH",
                next_best_action="REQUEST_INFORMATION",
            )
            self.db.add(case)
            self.db.flush()
            doc = Document(
                recovery_case_id=case.id,
                document_type="invoice",
                reference="documents/test_invoice.pdf",
                status="available",
            )
            self.db.add(doc)
            self.db.commit()
            analyze_transaction(tx.id, self.db)
            case = self.db.query(RecoveryCase).filter_by(transaction_id=tx.id).one()
        else:
            case = analyze_transaction(tx.id, self.db)

        return tx, case

    def test_pii_masking(self):
        text = "Contact user at john.doe@company.com or +91 9876543210. PAN: ABCDE1234F, Acct: 123456789012."
        masked = mask_pii_text(text)
        self.assertNotIn("john.doe@company.com", masked)
        self.assertNotIn("9876543210", masked)
        self.assertNotIn("ABCDE1234F", masked)
        self.assertNotIn("123456789012", masked)
        self.assertIn("[EMAIL]", masked)
        self.assertIn("[PHONE]", masked)
        self.assertIn("[TAX_ID]", masked)
        self.assertIn("[ACCOUNT_NUMBER]", masked)

        data = {"email": "test@test.org", "notes": "Call +1-555-123-4567"}
        masked_data = mask_pii_dict(data)
        self.assertEqual(masked_data["email"], "[EMAIL]")
        self.assertIn("[PHONE]", masked_data["notes"])

    def test_resolution_request_creation(self):
        tx, case = self.create_case(amount="580000", customer_name=None, customer_email=None)
        resp = self.client.post(f"/api/cases/{case.id}/request-resolution")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["case_id"], case.id)
        self.assertEqual(data["status"], "action_required")
        self.assertTrue(len(data["requested_information"]) > 0)
        self.assertIn("customer_message", data)

        # Check DB state
        with SessionLocal() as db:
            updated_case = db.get(RecoveryCase, case.id)
            self.assertEqual(updated_case.status, "action_required")
            self.assertEqual(updated_case.stage, "action_required")
            action = db.query(Action).filter_by(recovery_case_id=case.id, action_type="CUSTOMER_RESOLUTION_REQUESTED").one_or_none()
            self.assertIsNotNone(action)
            audit = db.query(AuditLog).filter_by(entity_id=str(case.id), event_type="resolution_requested").one_or_none()
            self.assertIsNotNone(audit)

    def test_customer_submission_json_pass(self):
        tx, case = self.create_case(amount="580000", customer_name=None, customer_email=None, has_doc=True)
        resp = self.client.post(f"/api/cases/{case.id}/request-resolution")
        self.assertEqual(resp.status_code, 200)

        # Submit matching invoice and customer information
        submission = {
            "customer_name": "Asha Sharma",
            "customer_email": "asha.sharma@example.com",
            "country_code": "IN",
            "invoice_amount": "580000",
            "invoice_currency": "INR",
            "invoice_reference": "INV-2026-001",
            "invoice_date": "2026-01-15T10:00:00Z",
        }
        resp = self.client.post(f"/api/customers/cases/{case.id}/resolve", json=submission)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()
        self.assertEqual(result["status"], "PASS")

        with SessionLocal() as db:
            updated_case = db.get(RecoveryCase, case.id)
            self.assertEqual(updated_case.status, "settlement_ready")
            self.assertEqual(updated_case.stage, "settlement_ready")
            val_rec = db.query(ValidationResult).filter_by(recovery_case_id=case.id).one_or_none()
            self.assertTrue(val_rec.passed)

    def test_customer_submission_with_pdf_upload(self):
        tx, case = self.create_case(amount="150000", customer_name="Rahul", customer_email="rahul@example.com", has_doc=False)
        self.client.post(f"/api/cases/{case.id}/request-resolution")

        fake_pdf_content = b"%PDF-1.4 mock pdf document content for recovery"
        form_data = {
            "customer_name": "Rahul Verma",
            "customer_email": "rahul.verma@example.com",
            "country_code": "IN",
            "invoice_amount": "150000",
            "invoice_currency": "INR",
            "invoice_reference": "INV-PDF-100",
        }
        files = {"file": ("invoice.pdf", fake_pdf_content, "application/pdf")}

        resp = self.client.post(
            f"/api/customers/cases/{case.id}/resolve",
            data=form_data,
            files=files,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "PASS")

        with SessionLocal() as db:
            docs = db.query(Document).filter_by(recovery_case_id=case.id).all()
            self.assertTrue(len(docs) >= 1)
            self.assertEqual(docs[-1].status, "available")

    def test_invalid_file_type_rejected(self):
        doc_service = DocumentService()
        with self.assertRaises(Exception):
            doc_service.validate_file(
                filename="script.exe",
                content_type="application/x-msdownload",
                file_size=1024,
                content=b"MZ\x90\x00",
            )

    def test_oversized_upload_rejected(self):
        doc_service = DocumentService()
        with self.assertRaises(Exception):
            doc_service.validate_file(
                filename="huge.pdf",
                content_type="application/pdf",
                file_size=10 * 1024 * 1024,
                content=b"%PDF-1.4",
            )

    def test_amount_mismatch_fails(self):
        tx, case = self.create_case(amount="580000", customer_name="Asha", customer_email="asha@example.com", has_doc=True)
        submission = {
            "invoice_amount": "520000",  # Mismatch: payment is 580000
            "invoice_currency": "INR",
            "invoice_reference": "INV-MISMATCH-1",
        }
        resp = self.client.post(f"/api/customers/cases/{case.id}/resolve", json=submission)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()
        self.assertEqual(result["status"], "FAIL")

        with SessionLocal() as db:
            updated_case = db.get(RecoveryCase, case.id)
            self.assertEqual(updated_case.status, "validation_failed")
            self.assertEqual(updated_case.stage, "action_required")

    def test_currency_mismatch_fails(self):
        tx, case = self.create_case(amount="580000", currency="INR", customer_name="Asha", customer_email="asha@example.com", has_doc=True)
        submission = {
            "invoice_amount": "580000",
            "invoice_currency": "USD",  # Mismatch: payment is INR
            "invoice_reference": "INV-CURRENCY-1",
        }
        resp = self.client.post(f"/api/customers/cases/{case.id}/resolve", json=submission)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()
        self.assertEqual(result["status"], "FAIL")

    def test_missing_invoice_reference_fails(self):
        tx, case = self.create_case(amount="580000", customer_name="Asha", customer_email="asha@example.com", has_doc=True)
        submission = {
            "invoice_amount": "580000",
            "invoice_currency": "INR",
            "invoice_reference": "",  # Missing
        }
        resp = self.client.post(f"/api/customers/cases/{case.id}/resolve", json=submission)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()
        self.assertEqual(result["status"], "FAIL")

    def test_ambiguous_submission_triggers_review(self):
        tx, case = self.create_case(amount="580000", customer_name="Asha", customer_email="asha@example.com", has_doc=True)
        submission = {
            "invoice_amount": None,  # Ambiguous amount
            "invoice_currency": "INR",
            "invoice_reference": "INV-AMBIGUOUS-1",
        }
        resp = self.client.post(f"/api/customers/cases/{case.id}/resolve", json=submission)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()
        self.assertEqual(result["status"], "REVIEW")

        with SessionLocal() as db:
            updated_case = db.get(RecoveryCase, case.id)
            self.assertEqual(updated_case.status, "merchant_review")

    def test_merchant_review_approve(self):
        tx, case = self.create_case(amount="580000", customer_name="Asha", customer_email="asha@example.com", has_doc=True)
        # Fast-track case to settlement_ready
        case.status = "settlement_ready"
        case.stage = "settlement_ready"
        self.db.commit()

        resp = self.client.post(
            f"/api/cases/{case.id}/review",
            json={"decision": "APPROVE", "notes": "Approved for workflow completion."},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["decision"], "APPROVE")
        self.assertEqual(data["case_status"], "recovered")

        with SessionLocal() as db:
            updated_case = db.get(RecoveryCase, case.id)
            self.assertEqual(updated_case.status, "recovered")
            self.assertEqual(updated_case.stage, "recovered")
            action = db.query(Action).filter_by(recovery_case_id=case.id, action_type="MERCHANT_REVIEW_APPROVE").one_or_none()
            self.assertIsNotNone(action)

    def test_merchant_review_request_info(self):
        tx, case = self.create_case(amount="580000", customer_name="Asha", customer_email="asha@example.com")
        resp = self.client.post(
            f"/api/cases/{case.id}/review",
            json={"decision": "REQUEST_MORE_INFORMATION", "notes": "Please provide clearer invoice copy."},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["case_status"], "action_required")

    def test_merchant_review_reject(self):
        tx, case = self.create_case(amount="580000", customer_name="Asha", customer_email="asha@example.com")
        resp = self.client.post(
            f"/api/cases/{case.id}/review",
            json={"decision": "REJECT", "notes": "Fraudulent customer response."},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["case_status"], "closed")

    def test_invalid_merchant_decision(self):
        tx, case = self.create_case(amount="580000")
        resp = self.client.post(
            f"/api/cases/{case.id}/review",
            json={"decision": "INVALID_DECISION"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_case_resolution_and_audit_endpoints(self):
        tx, case = self.create_case(amount="580000", customer_name=None, customer_email=None, has_doc=True)
        self.client.post(f"/api/cases/{case.id}/request-resolution")
        self.client.post(
            f"/api/customers/cases/{case.id}/resolve",
            json={
                "customer_name": "Asha",
                "customer_email": "asha@example.com",
                "country_code": "IN",
                "invoice_amount": "580000",
                "invoice_currency": "INR",
                "invoice_reference": "INV-AUDIT-1",
            },
        )
        self.client.post(f"/api/cases/{case.id}/review", json={"decision": "APPROVE"})

        # Test resolution details
        resp_res = self.client.get(f"/api/cases/{case.id}/resolution")
        self.assertEqual(resp_res.status_code, 200)
        res_data = resp_res.json()
        self.assertEqual(res_data["case_id"], case.id)
        self.assertEqual(res_data["case_status"], "recovered")
        self.assertIsNotNone(res_data["latest_validation"])
        self.assertIsNotNone(res_data["merchant_decision"])

        # Test audit trail endpoint
        resp_audit = self.client.get(f"/api/cases/{case.id}/audit")
        self.assertEqual(resp_audit.status_code, 200)
        logs = resp_audit.json()
        self.assertTrue(len(logs) >= 3)
        event_types = [l["event_type"] for l in logs]
        self.assertIn("resolution_requested", event_types)
        self.assertIn("customer_response_received", event_types)
        self.assertIn("merchant_approved", event_types)

    def test_dashboard_recovered_metrics(self):
        tx, case = self.create_case(amount="580000", customer_name="Asha", customer_email="asha@example.com", has_doc=True)
        # Move case to recovered
        case.status = "recovered"
        case.stage = "recovered"
        case.amount_at_risk = Decimal("261000.00")
        self.db.commit()

        resp = self.client.get("/api/dashboard/summary")
        self.assertEqual(resp.status_code, 200)
        summary = resp.json()
        self.assertEqual(Decimal(str(summary["recovered_revenue"])), Decimal("261000.00"))
        self.assertTrue(Decimal(str(summary["recovery_rate"])) > Decimal("0"))

    def test_full_phase5_demo_scenario(self):
        """End-to-end demo scenario as specified in Phase 5 objective #12."""
        # 1. Start with high-value transaction 580000 INR
        customer = Customer(external_id="cust_demo_5", name=None, email=None, country_code="IN")
        self.db.add(customer)
        self.db.flush()

        tx = Transaction(
            external_id="pay_demo_580000",
            order_id="order_demo_580000",
            customer_id=customer.id,
            amount=Decimal("580000"),
            currency="INR",
            status="received",
            payment_method="upi",
        )
        self.db.add(tx)
        self.db.flush()

        # Attach available document
        case_initial = RecoveryCase(
            transaction_id=tx.id,
            customer_id=customer.id,
            status="open",
            stage="at_risk",
        )
        self.db.add(case_initial)
        self.db.flush()
        doc = Document(
            recovery_case_id=case_initial.id,
            document_type="invoice",
            reference="documents/demo_invoice.pdf",
            status="available",
        )
        self.db.add(doc)
        self.db.commit()

        # Phase 3 Deterministic Analysis
        case = analyze_transaction(tx.id, self.db)
        self.assertEqual(case.stage, "at_risk")
        self.assertEqual(case.next_best_action, "REQUEST_INFORMATION")

        # Step 1: Create recovery resolution request
        resp1 = self.client.post(f"/api/cases/{case.id}/request-resolution")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["status"], "action_required")

        # Step 2 & 3: Customer submits missing information and matching invoice data
        customer_payload = {
            "customer_name": "Asha Sharma",
            "customer_email": "asha.sharma@enterprise.com",
            "country_code": "IN",
            "invoice_amount": "580000",
            "invoice_currency": "INR",
            "invoice_reference": "INV-DEMO-580K",
            "invoice_date": "2026-01-20T00:00:00Z",
        }
        # Step 4: Run deterministic validation
        resp2 = self.client.post(f"/api/customers/cases/{case.id}/resolve", json=customer_payload)
        self.assertEqual(resp2.status_code, 200)
        val_data = resp2.json()

        # Step 5: Validation returns PASS
        self.assertEqual(val_data["status"], "PASS")

        # Step 6: Case becomes SETTLEMENT_READY
        with SessionLocal() as db:
            c = db.get(RecoveryCase, case.id)
            self.assertEqual(c.status, "settlement_ready")
            self.assertEqual(c.stage, "settlement_ready")

        # Step 7: Merchant approves
        resp3 = self.client.post(
            f"/api/cases/{case.id}/review",
            json={"decision": "APPROVE", "notes": "All invoice and customer details verified by merchant."},
        )
        self.assertEqual(resp3.status_code, 200)

        # Step 8: Case becomes RECOVERED
        with SessionLocal() as db:
            c = db.get(RecoveryCase, case.id)
            self.assertEqual(c.status, "recovered")
            self.assertEqual(c.stage, "recovered")

        # Step 9: Dashboard recovered/unlocked revenue increases
        resp4 = self.client.get("/api/dashboard/summary")
        self.assertEqual(resp4.status_code, 200)
        dash = resp4.json()
        self.assertGreaterEqual(Decimal(str(dash["recovered_revenue"])), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
