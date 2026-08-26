#!/usr/bin/env python3
"""Seed staging PostgreSQL with 1000+ transactions, 300+ cases, 150+ disputes, 200+ settlements, 800+ audit logs."""

import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

os.environ["DATABASE_URL"] = "postgresql+psycopg2://postgres@127.0.0.1:5433/recoverx_staging"

from app.core.security import hash_password
from app.database.connection import Base, engine
from app.database.session import SessionLocal
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.dispute import Dispute
from app.models.document import Document
from app.models.merchant import Merchant
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.models.user import User


def seed_staging():
    print("[*] Recreating all tables on PostgreSQL recoverx_staging...")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    db = SessionLocal()
    try:
        # 1. Seed Merchants
        m1 = db.scalar(select(Merchant).where(Merchant.id == 1))
        if not m1:
            m1 = Merchant(id=1, name="Acme Global Commerce", country_code="IN", currency="INR", is_active=True)
            db.add(m1)
        m2 = db.scalar(select(Merchant).where(Merchant.id == 2))
        if not m2:
            m2 = Merchant(id=2, name="Nexus Retail US", country_code="US", currency="USD", is_active=True)
            db.add(m2)
        db.commit()

        # 2. Seed Users
        u1 = db.scalar(select(User).where(User.id == 1))
        if not u1:
            u1 = User(
                id=1,
                merchant_id=1,
                email="admin@merchant.com",
                hashed_password=hash_password("admin123456"),
                full_name="Merchant 1 Admin",
                role="merchant_admin",
                is_active=True,
            )
            db.add(u1)
        u2 = db.scalar(select(User).where(User.id == 2))
        if not u2:
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

        # 3. Seed Customers
        customers = []
        for i in range(1, 101):
            c = Customer(
                external_id=f"cust_staging_{i:04d}",
                name=f"Enterprise Client {i}",
                email=f"client_{i}@enterprise.example.com",
                country_code="IN",
            )
            customers.append(c)
        db.add_all(customers)
        db.commit()

        # 4. Seed 1,000+ Transactions
        print("[*] Seeding 1,050 Transactions...")
        now = datetime.now(UTC)
        transactions = []
        statuses = ["captured", "action_required", "failed", "authorized", "disputed"]
        currencies = ["INR", "USD", "EUR", "GBP"]

        for i in range(1, 1051):
            status = statuses[i % len(statuses)]
            curr = currencies[i % len(currencies)]
            amt = Decimal(f"{((i * 37) % 500000 + 1000)}.00")
            cust_id = customers[i % len(customers)].id

            tx = Transaction(
                merchant_id=1 if i % 10 != 0 else 2,
                customer_id=cust_id,
                external_id=f"pay_staging_{i:06d}_{uuid4().hex[:6]}",
                order_id=f"order_staging_{i:06d}",
                amount=amt,
                currency=curr,
                status=status,
                payment_method="card" if i % 2 == 0 else "upi",
                country_code="IN" if curr == "INR" else "US",
                created_at=now - timedelta(hours=i),
            )
            transactions.append(tx)
        db.add_all(transactions)
        db.commit()

        # 5. Seed 350 Recovery Cases
        print("[*] Seeding 350 Recovery Cases...")
        cases = []
        priorities = ["HIGH", "MEDIUM", "LOW"]
        case_statuses = ["action_required", "merchant_review", "recovered", "settlement_ready", "closed_unresolved"]

        for i in range(350):
            tx = transactions[i]
            prio = priorities[i % 3]
            c_status = case_statuses[i % len(case_statuses)]
            rc = RecoveryCase(
                merchant_id=tx.merchant_id,
                transaction_id=tx.id,
                customer_id=tx.customer_id,
                status=c_status,
                stage="at_risk" if c_status in {"action_required", "merchant_review"} else "resolved",
                priority=prio,
                amount_at_risk=tx.amount,
                recovery_probability=Decimal(f"0.{70 + (i % 25)}0"),
                next_best_action="SUBMIT_REPRESENTMENT" if i % 2 == 0 else "REQUEST_INVOICE",
                created_at=now - timedelta(hours=i),
            )
            cases.append(rc)
        db.add_all(cases)
        db.commit()

        # 6. Seed 180 Disputes
        print("[*] Seeding 180 Disputes...")
        disputes = []
        disp_statuses = ["action_required", "under_review", "won", "lost", "closed"]
        reason_codes = ["merchandise_not_received", "unauthorized_transaction", "fraudulent", "duplicate_charge"]

        for i in range(180):
            tx = transactions[i]
            d_status = disp_statuses[i % len(disp_statuses)]
            disp = Dispute(
                merchant_id=tx.merchant_id,
                transaction_id=tx.id,
                razorpay_dispute_id=f"disp_staging_{i:05d}_{uuid4().hex[:6]}",
                payment_id=tx.external_id,
                amount=tx.amount,
                currency=tx.currency,
                reason_code=reason_codes[i % len(reason_codes)],
                status=d_status,
                respond_by=now + timedelta(hours=48 + i),
                deadline_status="safe" if i % 3 == 0 else "approaching",
                priority="HIGH" if tx.amount >= Decimal("100000.00") else "MEDIUM",
                created_at=now - timedelta(days=i % 30),
            )
            disputes.append(disp)
        db.add_all(disputes)
        db.commit()

        # 7. Seed 220 Settlements & Reconciliation Records
        print("[*] Seeding 220 Settlements...")
        settlements = []
        settle_statuses = ["processed", "on_hold", "failed", "partially_processed"]
        for i in range(220):
            s_status = settle_statuses[i % len(settle_statuses)]
            amt = Decimal(f"{(i * 12000 + 50000)}.00")
            tax = Decimal(f"{(amt * Decimal('0.018')):.2f}")
            fees = Decimal(f"{(amt * Decimal('0.020')):.2f}")

            st = Settlement(
                merchant_id=1,
                razorpay_settlement_id=f"setl_staging_{i:05d}_{uuid4().hex[:6]}",
                utr=f"UTR{i:08d}{uuid4().hex[:4].upper()}",
                amount=amt,
                fees=fees,
                tax=tax,
                currency="INR",
                status=s_status,
                settled_at=now - timedelta(days=i % 45),
                created_at=now - timedelta(days=i % 45),
            )
            settlements.append(st)
        db.add_all(settlements)
        db.commit()

        # 8. Seed 850 Audit Records
        print("[*] Seeding 850 Audit Log Records...")
        audit_logs = []
        event_types = [
            "CASE_ANALYZED",
            "EVIDENCE_SUBMITTED",
            "MERCHANT_APPROVED",
            "SETTLEMENT_SYNCED",
            "RECONCILIATION_FLAGGED",
            "DISPUTE_CONTESTED",
        ]
        for i in range(850):
            al = AuditLog(
                merchant_id=1,
                entity_type="recovery_case" if i % 2 == 0 else "dispute",
                entity_id=str((i % 350) + 1),
                event_type=event_types[i % len(event_types)],
                details=f'{{"step": {i}, "status": "verified", "timestamp": "{now.isoformat()}"}}',
                created_at=now - timedelta(hours=i % 500),
            )
            audit_logs.append(al)
        db.add_all(audit_logs)
        db.commit()

        print("[PASS] Successfully seeded PostgreSQL staging database with:")
        print(f"    - Transactions: {db.scalar(select(func.count(Transaction.id)))}")
        print(f"    - Recovery Cases: {db.scalar(select(func.count(RecoveryCase.id)))}")
        print(f"    - Disputes: {db.scalar(select(func.count(Dispute.id)))}")
        print(f"    - Settlements: {db.scalar(select(func.count(Settlement.id)))}")
        print(f"    - Audit Logs: {db.scalar(select(func.count(AuditLog.id)))}")

    finally:
        db.close()


if __name__ == "__main__":
    from sqlalchemy import func, select
    seed_staging()
