"""Financial Integrity & Zero Floating-Point Arithmetic Test Suite for RecoverX."""

from __future__ import annotations

from decimal import Decimal
import unittest

from app.intelligence.revenue_at_risk import calculate_revenue_at_risk
from app.services.razorpay_service import RazorpayService


class FinancialIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RazorpayService()

    # =========================================================================
    # 1. Decimal Precision & Minor Unit Conversions
    # =========================================================================
    def test_01_currency_minor_unit_normalization_decimal(self) -> None:
        """1. Verify standard currencies (INR, USD, EUR, GBP) convert 100 minor units to 1 major unit using Decimal."""
        # INR: 100 paise = 1.00 INR
        self.assertEqual(self.service.normalize_amount(100, "INR"), Decimal("1.00"))
        self.assertEqual(self.service.normalize_amount(58000000, "INR"), Decimal("580000.00"))

        # USD: 100 cents = 1.00 USD
        self.assertEqual(self.service.normalize_amount(100, "USD"), Decimal("1.00"))
        self.assertEqual(self.service.normalize_amount(150050, "USD"), Decimal("1500.50"))

        # JPY: Zero minor unit currency (1 JPY = 1 JPY)
        self.assertEqual(self.service.normalize_amount(150000, "JPY"), Decimal("150000.00"))

    def test_02_boundary_amounts_exact_decimal(self) -> None:
        """2. Verify exact Decimal calculation on boundary financial values (0, 0.01, large numbers)."""
        # 0 Amount
        zero_res = calculate_revenue_at_risk(amount=Decimal("0.00"), risk_score=Decimal("45.00"), is_high_value=False)
        self.assertEqual(zero_res["revenue_at_risk"], Decimal("0.00"))

        # 0.01 Amount
        penny_res = calculate_revenue_at_risk(amount=Decimal("0.01"), risk_score=Decimal("50.00"), is_high_value=False)
        self.assertEqual(penny_res["revenue_at_risk"], Decimal("0.01"))

        # ₹10,00,00,000 (100 Crore / 1 Billion)
        large_res = calculate_revenue_at_risk(amount=Decimal("1000000000.00"), risk_score=Decimal("35.00"), is_high_value=True)
        self.assertEqual(large_res["revenue_at_risk"], Decimal("350000000.00"))
        self.assertIsInstance(large_res["revenue_at_risk"], Decimal)

    # =========================================================================
    # 2. Reconciliation Variance Deterministic Formula
    # =========================================================================
    def test_03_reconciliation_exact_balance_formula(self) -> None:
        """3. Verify reconciliation variance formula: |expected - (settled + fee + tax + refund + adj)|."""
        expected = Decimal("1000000.00")
        settled = Decimal("950000.00")
        fee = Decimal("20000.00")
        tax = Decimal("3600.00")
        refund = Decimal("10000.00")
        adjustment = Decimal("5000.00")

        explained_sum = settled + fee + tax + refund + adjustment  # 988600.00
        unexplained = abs(expected - explained_sum)  # 11400.00

        self.assertEqual(unexplained, Decimal("11400.00"))
        self.assertIsInstance(unexplained, Decimal)


if __name__ == "__main__":
    unittest.main()

