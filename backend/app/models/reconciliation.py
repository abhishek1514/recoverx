from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.recovery_case import RecoveryCase
    from app.models.settlement import Settlement
    from app.models.transaction import Transaction


class ReconciliationRecord(Base):
    __tablename__ = "reconciliation_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True, default=1)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True, nullable=True)
    settlement_id: Mapped[int | None] = mapped_column(ForeignKey("settlements.id"), index=True, nullable=True)
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    settled_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    adjustment_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    discrepancy_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    discrepancy_type: Mapped[str] = mapped_column(String(50), default="none")
    status: Mapped[str] = mapped_column(String(50), default="flagged", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    merchant: Mapped["Merchant"] = relationship()
    transaction: Mapped["Transaction | None"] = relationship()
    settlement: Mapped["Settlement | None"] = relationship(back_populates="reconciliation_records")
    recovery_cases: Mapped[list["RecoveryCase"]] = relationship(back_populates="reconciliation_record")

