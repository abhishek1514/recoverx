from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.merchant import Merchant
    from app.models.recovery_case import RecoveryCase
    from app.models.risk_assessment import RiskAssessment


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True, default=1)
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    order_id: Mapped[str | None] = mapped_column(String(100), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    payment_method: Mapped[str | None] = mapped_column(String(50))
    event_type: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    merchant: Mapped["Merchant | None"] = relationship(back_populates="transactions")
    customer: Mapped["Customer | None"] = relationship(back_populates="transactions")
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="transaction")
    recovery_cases: Mapped[list["RecoveryCase"]] = relationship(back_populates="transaction")
