from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings
from app.core.security import hash_password

logger = logging.getLogger(__name__)

settings = get_settings()

connect_args: dict[str, Any] = {}
engine_kwargs: dict[str, Any] = {
    "future": True,
    "echo": False,
}

if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    from sqlalchemy.pool import NullPool
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs.update({
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
    })

engine_kwargs["connect_args"] = connect_args
engine = create_engine(settings.database_url, **engine_kwargs)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    """Create all tables and non-destructively ensure new required columns exist."""
    from app.models.action import Action
    from app.models.audit_log import AuditLog
    from app.models.customer import Customer
    from app.models.dispute import Dispute
    from app.models.document import Document
    from app.models.merchant import Merchant
    from app.models.reconciliation import ReconciliationRecord
    from app.models.recovery_case import RecoveryCase
    from app.models.risk_assessment import RiskAssessment
    from app.models.settlement import Settlement
    from app.models.transaction import Transaction
    from app.models.user import User
    from app.models.webhook_event import WebhookEvent

    Base.metadata.create_all(bind=engine)

    additions = {
        "transactions": {
            "merchant_id": "INTEGER DEFAULT 1",
            "order_id": "VARCHAR(100)",
            "event_type": "VARCHAR(100)",
        },
        "risk_assessments": {
            "risk_score": "NUMERIC(5, 2)",
            "readiness_status": "VARCHAR(50)",
            "risk_reasons": "TEXT",
            "missing_information": "TEXT",
            "confidence": "NUMERIC(4, 3)",
        },
        "recovery_cases": {
            "merchant_id": "INTEGER DEFAULT 1",
            "exception_type": "VARCHAR(50) DEFAULT 'settlement_hold'",
            "dispute_id": "INTEGER",
            "settlement_id": "INTEGER",
            "reconciliation_record_id": "INTEGER",
            "recovery_probability": "NUMERIC(4, 3)",
            "priority": "VARCHAR(20)",
            "next_best_action": "VARCHAR(100)",
        },
        "documents": {
            "merchant_id": "INTEGER DEFAULT 1",
            "dispute_id": "INTEGER",
            "file_name": "VARCHAR(255)",
            "file_size_bytes": "INTEGER",
        },
        "disputes": {
            "priority": "VARCHAR(50) DEFAULT 'MEDIUM'",
            "deadline_status": "VARCHAR(50) DEFAULT 'unknown'",
            "contest_status": "VARCHAR(50) DEFAULT 'draft'",
            "contest_summary": "VARCHAR(2000)",
            "contest_submitted_at": "DATETIME",
            "submission_error": "VARCHAR(255)",
            "evidence_completeness": "VARCHAR(50) DEFAULT 'incomplete'",
            "validation_status": "VARCHAR(50) DEFAULT 'pending'",
            "validation_notes": "VARCHAR(2000)",
        },
        "audit_logs": {
            "merchant_id": "INTEGER DEFAULT 1",
        },
        "actions": {
            "reason": "TEXT",
            "confidence": "NUMERIC(4, 3)",
        },
    }
    with engine.begin() as connection:
        for table, table_additions in additions.items():
            try:
                columns = {column["name"] for column in inspect(engine).get_columns(table)}
                for name, definition in table_additions.items():
                    if name not in columns:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
            except Exception as e:
                logger.debug("Schema check note on table %s: %s", table, e)

    # Seed default merchant & user if not present (ensures seamless demo & test suites)
    with Session(engine) as session:
        try:
            default_merchant = session.scalar(select(Merchant).where(Merchant.id == 1))
            if default_merchant is None:
                default_merchant = Merchant(
                    id=1,
                    name="RecoverX Global Merchant",
                    country_code="IN",
                    currency="INR",
                    is_active=True,
                )
                session.add(default_merchant)
                session.flush()

            default_user = session.scalar(select(User).where(User.email == "admin@merchant.com"))
            if default_user is None:
                default_user = User(
                    merchant_id=default_merchant.id,
                    email="admin@merchant.com",
                    hashed_password=hash_password("admin123456"),
                    full_name="Operations Admin",
                    role="merchant_admin",
                    is_active=True,
                )
                session.add(default_user)

            session.commit()
        except Exception:
            session.rollback()
