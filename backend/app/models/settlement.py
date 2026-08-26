from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.reconciliation import ReconciliationRecord
    from app.models.recovery_case import RecoveryCase


class Settlement(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        UniqueConstraint("merchant_id", "razorpay_settlement_id", name="uq_merchant_razorpay_settlement_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True, default=1)
    razorpay_settlement_id: Mapped[str] = mapped_column(String(100), index=True)
    utr: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    fees: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(50), default="processed", index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    merchant: Mapped["Merchant"] = relationship()
    recovery_cases: Mapped[list["RecoveryCase"]] = relationship(back_populates="settlement")
    reconciliation_records: Mapped[list["ReconciliationRecord"]] = relationship(back_populates="settlement")

