from __future__ import annotations

import logging
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine_options: dict = {"future": True}

raw_db_url = settings.database_url
# Render & Heroku provide postgres:// URLs; SQLAlchemy 1.4+ / 2.0 requires postgresql://
if raw_db_url.startswith("postgres://"):
    db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
else:
    db_url = raw_db_url

if db_url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL production connection pool configuration
    engine_options["pool_size"] = settings.db_pool_size
    engine_options["max_overflow"] = settings.db_max_overflow
    engine_options["pool_pre_ping"] = True
    engine_options["pool_recycle"] = 1800

engine = create_engine(db_url, **engine_options)


def ensure_schema() -> None:
    """Create the schema and apply additive migrations without deleting data."""
    from app.core.security import hash_password
    from app.models.merchant import Merchant
    from app.models.user import User

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
            "recovery_probability": "NUMERIC(4, 3)",
            "priority": "VARCHAR(20)",
            "next_best_action": "VARCHAR(100)",
        },
        "documents": {
            "merchant_id": "INTEGER DEFAULT 1",
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
        except Exception as e:
            session.rollback()
            logger.debug("Default merchant seed note: %s", e)
