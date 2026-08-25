import os
import tempfile
import unittest
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Keep the same isolated configuration used by the webhook tests, regardless
# of discovery order. This module itself uses an in-memory database.
TEST_DB = __import__("pathlib").Path(tempfile.gettempdir()) / "recoverx_webhook_tests.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_example"
os.environ["RAZORPAY_KEY_SECRET"] = "test_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"

import app.models
from app.ai.llm_client import AIUnavailableError
from app.ai.schemas import AIExplanation
from app.database.connection import Base
from app.models.customer import Customer
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.services.ai_policy_guard import apply_policy_guard
from app.services.ai_service import build_ai_context, generate_case_explanation


def valid_ai() -> AIExplanation:
    return AIExplanation(
        risk_explanation="Customer information is incomplete.",
        recovery_explanation="Existing payment context supports a follow-up.",
        recommended_action_explanation="Request the missing information.",
        merchant_message="Review the missing customer information.",
        customer_message="Please provide the missing information.",
        confidence=Decimal("0.80"),
    )


class StaticAIClient:
    def __init__(self, value):
        self.value = value
        self.context = None

    def generate(self, context):
        self.context = context
        return self.value


class UnavailableAIClient:
    def generate(self, context):
        raise AIUnavailableError("provider unavailable")


class AIServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://")
        cls.Session = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.db = self.Session()
        customer = Customer(external_id="cust_ai", name="Sensitive Name", email="sensitive@example.com", country_code="IN")
        self.db.add(customer)
        self.db.flush()
        transaction = Transaction(external_id="pay_ai", customer_id=customer.id, amount=Decimal("580000"), currency="INR", status="received", payment_method="upi")
        self.db.add(transaction)
        self.db.flush()
        self.case = RecoveryCase(transaction_id=transaction.id, customer_id=customer.id, status="open", stage="at_risk", amount_at_risk=Decimal("261000"), recovery_probability=Decimal("0.82"), priority="HIGH", next_best_action="REQUEST_INFORMATION")
        self.db.add(self.case)
        self.db.add(RiskAssessment(transaction_id=transaction.id, risk_score=Decimal("45"), settlement_risk_score=Decimal("45"), readiness_status="AT_RISK", risk_reasons='["Customer information is incomplete."]', missing_information='["customer_information"]', confidence=Decimal("0.87"), revenue_at_risk=Decimal("261000"), recovery_probability=Decimal("0.82"), status="AT_RISK"))
        self.db.commit()
        self.transaction = transaction
        self.assessment = self.db.query(RiskAssessment).one()

    def tearDown(self):
        self.db.close()

    def test_ai_response_schema_validation(self):
        self.assertEqual(valid_ai().confidence, Decimal("0.80"))
        with self.assertRaises(ValidationError):
            AIExplanation(risk_explanation="x", recovery_explanation="x", recommended_action_explanation="x", merchant_message="x", customer_message="x", confidence=Decimal("1.1"))

    def test_policy_guard_preserves_financial_values(self):
        result = apply_policy_guard(valid_ai(), risk_score=Decimal("45"), revenue_at_risk=Decimal("261000"), recovery_probability=Decimal("0.82"), deterministic_action="MERCHANT_REVIEW", suggested_action="REQUEST_INFORMATION")
        self.assertEqual(result["risk_score"], Decimal("45"))
        self.assertEqual(result["revenue_at_risk"], Decimal("261000"))
        self.assertEqual(result["recovery_probability"], Decimal("0.82"))
        self.assertEqual(result["next_best_action"], "MERCHANT_REVIEW")
        self.assertTrue(result["action_overridden"])

    def test_ai_unavailable_fallback(self):
        result = generate_case_explanation(self.case.id, self.db, UnavailableAIClient())
        self.assertEqual(result.ai_status, "unavailable")
        self.assertIsNone(result.ai)
        self.assertEqual(result.risk_score, Decimal("45"))
        self.assertEqual(result.next_best_action, "REQUEST_INFORMATION")

    def test_invalid_ai_response_is_handled(self):
        result = generate_case_explanation(self.case.id, self.db, StaticAIClient({"risk_explanation": "missing fields"}))
        self.assertEqual(result.ai_status, "unavailable")

    def test_minimal_ai_context_excludes_pii(self):
        context = build_ai_context(self.case, self.transaction, self.assessment)
        serialized = str(context)
        self.assertNotIn("sensitive@example.com", serialized)
        self.assertNotIn("Sensitive Name", serialized)
        self.assertNotIn("cust_ai", serialized)

    def test_valid_ai_response_retains_deterministic_values(self):
        result = generate_case_explanation(self.case.id, self.db, StaticAIClient(valid_ai()))
        self.assertEqual(result.ai_status, "available")
        self.assertEqual(result.risk_score, Decimal("45"))
        self.assertEqual(result.revenue_at_risk, Decimal("261000"))
        self.assertEqual(result.recovery_probability, Decimal("0.82"))
        self.assertEqual(result.next_best_action, "REQUEST_INFORMATION")


if __name__ == "__main__":
    unittest.main()
