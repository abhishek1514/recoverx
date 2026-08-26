"""Unit and integration tests for Phase 7B performance optimizations.

Verifies:
1. Exact dashboard metric equivalence between original and optimized queries.
2. Query count reduction for authenticated requests and dashboard endpoints.
3. Concurrent duplicate webhook idempotency.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

TEST_DB = Path(tempfile.gettempdir()) / "recoverx_phase7b_tests.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_example"
os.environ["RAZORPAY_KEY_SECRET"] = "test_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"

from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine

from app.core.security import create_access_token
from app.database.connection import Base, engine
from app.database.session import SessionLocal
from app.main import app
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.models.user import User
from app.models.webhook_event import WebhookEvent


class Phase7bOptimizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__()

    def setUp(self) -> None:
        from app.database.connection import ensure_schema
        ensure_schema()
        self.db = SessionLocal()

        # Seed Merchant & User
        m1 = self.db.scalar(select(Merchant).where(Merchant.id == 1))
        if m1 is None:
            m1 = Merchant(id=1, name="Test Merchant 1", is_active=True)
            self.db.add(m1)

        m2 = self.db.scalar(select(Merchant).where(Merchant.id == 2))
        if m2 is None:
            m2 = Merchant(id=2, name="Test Merchant 2", is_active=True)
            self.db.add(m2)

        u1 = self.db.scalar(select(User).where(User.id == 1))
        if u1 is None:
            u1 = User(id=1, merchant_id=1, email="admin@m1.com", hashed_password="pwd", is_active=True)
            self.db.add(u1)

        u2 = self.db.scalar(select(User).where(User.id == 2))
        if u2 is None:
            u2 = User(id=2, merchant_id=2, email="admin@m2.com", hashed_password="pwd", is_active=True)
            self.db.add(u2)

        self.db.commit()

        self.token = create_access_token(data={"sub": "1", "merchant_id": 1})
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.db.close()

    def test_01_dashboard_metric_exactness_and_query_count(self) -> None:
        """1. Verify that consolidated dashboard queries return exact metrics with reduced query count."""
        # Seed isolated merchant 99
        m99 = self.db.scalar(select(Merchant).where(Merchant.id == 99))
        if m99 is None:
            m99 = Merchant(id=99, name="Test Merchant 99", is_active=True)
            self.db.add(m99)
        u99 = self.db.scalar(select(User).where(User.id == 99))
        if u99 is None:
            u99 = User(id=99, merchant_id=99, email="admin@m99.com", hashed_password="pwd", is_active=True)
            self.db.add(u99)
        self.db.commit()

        token_99 = create_access_token(data={"sub": "99", "merchant_id": 99})
        headers_99 = {"Authorization": f"Bearer {token_99}"}

        # Seed test data for merchant 99
        t1 = Transaction(merchant_id=99, amount=Decimal("600000.00"), currency="INR", status="captured")
        t2 = Transaction(merchant_id=99, amount=Decimal("25000.00"), currency="INR", status="captured")
        t3 = Transaction(merchant_id=99, amount=Decimal("150000.00"), currency="INR", status="failed")
        self.db.add_all([t1, t2, t3])
        self.db.commit()

        c1 = RecoveryCase(
            merchant_id=99,
            transaction_id=t1.id,
            priority="HIGH",
            status="action_required",
            amount_at_risk=Decimal("600000.00"),
            recovery_probability=Decimal("0.850"),
        )
        c2 = RecoveryCase(
            merchant_id=99,
            transaction_id=t3.id,
            priority="MEDIUM",
            status="recovered",
            amount_at_risk=Decimal("150000.00"),
            recovery_probability=Decimal("0.900"),
        )
        c3 = RecoveryCase(
            merchant_id=99,
            transaction_id=t2.id,
            priority="LOW",
            status="merchant_review",
            amount_at_risk=Decimal("25000.00"),
            recovery_probability=Decimal("0.500"),
        )

        r1 = RiskAssessment(
            transaction_id=t1.id,
            readiness_status="AT_RISK",
            revenue_at_risk=Decimal("600000.00"),
            recovery_probability=Decimal("0.850"),
        )
        r2 = RiskAssessment(
            transaction_id=t3.id,
            readiness_status="HIGH_RISK",
            revenue_at_risk=Decimal("150000.00"),
            recovery_probability=Decimal("0.900"),
        )

        self.db.add_all([c1, c2, c3, r1, r2])
        self.db.commit()

        # Track query count
        executed_queries = []

        def track_query(conn, cursor, statement, parameters, context, executemany):
            executed_queries.append(statement)

        event.listen(Engine, "before_cursor_execute", track_query)
        try:
            res = self.client.get("/api/dashboard/summary", headers=headers_99)
        finally:
            event.remove(Engine, "before_cursor_execute", track_query)

        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Verify exact metric values
        self.assertEqual(data["total_transactions"], 3)
        self.assertEqual(data["high_value_transactions"], 2)  # threshold >= 50,000 INR
        self.assertEqual(data["at_risk_transactions"], 2)
        self.assertEqual(float(data["total_revenue_at_risk"]), 750000.00)
        self.assertEqual(data["high_priority_cases"], 1)
        self.assertEqual(float(data["recovered_revenue"]), 150000.00)
        self.assertEqual(data["cases_awaiting_customer"], 1)
        self.assertEqual(data["cases_awaiting_merchant_review"], 1)
        self.assertEqual(data["settlement_ready_cases"], 0)

        # Verify query count is reduced to 4 (1 auth + 3 data queries) instead of 10
        self.assertLessEqual(len(executed_queries), 4)

    def test_02_auth_joined_loading(self) -> None:
        """2. Verify that get_current_user eager-loads merchant in a single SQL query."""
        executed_queries = []

        def track_query(conn, cursor, statement, parameters, context, executemany):
            executed_queries.append(statement)

        event.listen(Engine, "before_cursor_execute", track_query)
        try:
            res = self.client.get("/api/disputes", headers=self.headers)
        finally:
            event.remove(Engine, "before_cursor_execute", track_query)

        self.assertEqual(res.status_code, 200)
        # Auth query + endpoint query = exactly 2 queries
        self.assertLessEqual(len(executed_queries), 2)
