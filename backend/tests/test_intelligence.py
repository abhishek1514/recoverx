import os
import tempfile
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Keep the same isolated settings used by the webhook tests regardless of
# unittest discovery order. The intelligence tests themselves use in-memory DBs.
TEST_DB = __import__("pathlib").Path(tempfile.gettempdir()) / "recoverx_webhook_tests.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_example"
os.environ["RAZORPAY_KEY_SECRET"] = "test_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"

import app.models  # Registers all models on Base metadata.
from app.intelligence.next_best_action import select_next_best_action
from app.intelligence.recovery_probability import estimate_recovery_probability
from app.intelligence.revenue_at_risk import calculate_revenue_at_risk
from app.intelligence.settlement_readiness import analyze_settlement_readiness
from app.database.connection import Base
from app.models.customer import Customer
from app.models.document import Document
from app.models.recovery_case import RecoveryCase
from app.models.transaction import Transaction
from app.services.recovery_service import analyze_transaction


class IntelligenceEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine("sqlite://")
        cls.Session = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.db = self.Session()

    def tearDown(self) -> None:
        self.db.close()

    def add_transaction(self, amount: str = "5000", status: str = "received", customer: Customer | None = None) -> Transaction:
        if customer is not None:
            self.db.add(customer)
            self.db.flush()
        transaction = Transaction(
            external_id=f"pay_{amount}_{status}", customer_id=customer.id if customer else None,
            amount=Decimal(amount), currency="INR", status=status, payment_method="upi",
        )
        self.db.add(transaction)
        self.db.commit()
        return transaction

    def add_available_document(self, transaction: Transaction) -> None:
        recovery_case = RecoveryCase(transaction_id=transaction.id, customer_id=transaction.customer_id)
        self.db.add(recovery_case)
        self.db.flush()
        self.db.add(Document(recovery_case_id=recovery_case.id, document_type="invoice", status="available"))
        self.db.commit()

    def test_low_risk_normal_transaction(self) -> None:
        customer = Customer(external_id="cust_low", name="Asha", email="asha@example.com", country_code="IN")
        transaction = self.add_transaction(customer=customer)
        self.add_available_document(transaction)
        readiness = analyze_settlement_readiness(transaction, customer, True, previous_transaction_count=1)
        self.assertEqual(readiness["readiness_status"], "READY")
        self.assertEqual(readiness["risk_score"], Decimal("0"))

    def test_high_value_transaction(self) -> None:
        customer = Customer(external_id="cust_high", name="Asha", email="asha@example.com", country_code="IN")
        transaction = self.add_transaction(amount="580000", customer=customer)
        readiness = analyze_settlement_readiness(transaction, customer, True, previous_transaction_count=1)
        self.assertTrue(readiness["is_high_value"])
        self.assertEqual(readiness["risk_score"], Decimal("20"))

    def test_missing_customer_information(self) -> None:
        customer = Customer(external_id="cust_partial")
        transaction = self.add_transaction(customer=customer)
        readiness = analyze_settlement_readiness(transaction, customer, True, previous_transaction_count=1)
        self.assertIn("customer_information", readiness["missing_information"])

    def test_missing_document(self) -> None:
        customer = Customer(external_id="cust_docs", name="Asha", email="asha@example.com", country_code="IN")
        transaction = self.add_transaction(customer=customer)
        readiness = analyze_settlement_readiness(transaction, customer, False, previous_transaction_count=1)
        self.assertIn("invoice_or_document", readiness["missing_information"])

    def test_high_risk_transaction(self) -> None:
        transaction = self.add_transaction(amount="580000", status="failed")
        readiness = analyze_settlement_readiness(transaction, None, False, previous_transaction_count=0)
        self.assertEqual(readiness["readiness_status"], "HIGH_RISK")

    def test_ready_transaction_action(self) -> None:
        action = select_next_best_action({"risk_score": Decimal("0"), "readiness_status": "READY", "missing_information": []})
        self.assertEqual(action["action"], "NO_ACTION")

    def test_revenue_at_risk_exact_arithmetic(self) -> None:
        result = calculate_revenue_at_risk(Decimal("580000"), Decimal("82"), True)
        self.assertEqual(result["risk_probability"], Decimal("0.82"))
        self.assertEqual(result["revenue_at_risk"], Decimal("475600.00"))
        self.assertEqual(result["priority"], "HIGH")

    def test_recovery_probability(self) -> None:
        customer = Customer(external_id="cust_probability", name="Asha", email="asha@example.com", country_code="IN")
        transaction = self.add_transaction(amount="580000", customer=customer)
        readiness = analyze_settlement_readiness(transaction, customer, True, previous_transaction_count=1)
        result = estimate_recovery_probability(transaction, customer, True, readiness)
        self.assertEqual(result["recovery_probability"], Decimal("0.95"))

    def test_next_best_action_selection(self) -> None:
        result = select_next_best_action({"risk_score": Decimal("40"), "readiness_status": "AT_RISK", "missing_information": ["customer_information"]})
        self.assertEqual(result["action"], "REQUEST_INFORMATION")

    def test_full_demo_transaction_to_recovery_case(self) -> None:
        customer = Customer(external_id="cust_demo")
        transaction = self.add_transaction(amount="580000", status="received", customer=customer)
        self.add_available_document(transaction)
        recovery_case = analyze_transaction(transaction.id, self.db)
        self.assertEqual(recovery_case.stage, "at_risk")
        self.assertGreater(recovery_case.amount_at_risk, Decimal("0"))
        self.assertGreater(recovery_case.recovery_probability, Decimal("0.70"))
        self.assertEqual(recovery_case.next_best_action, "REQUEST_INFORMATION")


if __name__ == "__main__":
    unittest.main()
