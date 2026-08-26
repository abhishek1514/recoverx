from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.dispute import Dispute
    from app.models.merchant import Merchant
    from app.models.reconciliation import ReconciliationRecord
    from app.models.settlement import Settlement
    from app.models.transaction import Transaction


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"
    __table_args__ = (
        Index("ix_recovery_cases_merchant_status", "merchant_id", "status"),
        Index("ix_recovery_cases_merchant_priority", "merchant_id", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True, default=1)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True, nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True, nullable=True)
    exception_type: Mapped[str] = mapped_column(String(50), default="settlement_hold", index=True)
    dispute_id: Mapped[int | None] = mapped_column(ForeignKey("disputes.id"), index=True, nullable=True)
    settlement_id: Mapped[int | None] = mapped_column(ForeignKey("settlements.id"), index=True, nullable=True)
    reconciliation_record_id: Mapped[int | None] = mapped_column(ForeignKey("reconciliation_records.id"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    stage: Mapped[str] = mapped_column(String(100), default="settlement_risk", index=True)
    amount_at_risk: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    recovery_probability: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    priority: Mapped[str | None] = mapped_column(String(20), index=True)
    next_best_action: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    merchant: Mapped["Merchant | None"] = relationship(back_populates="recovery_cases")
    transaction: Mapped["Transaction | None"] = relationship(back_populates="recovery_cases")
    customer: Mapped["Customer | None"] = relationship(back_populates="recovery_cases")
    dispute: Mapped["Dispute | None"] = relationship(back_populates="recovery_cases")
    settlement: Mapped["Settlement | None"] = relationship(back_populates="recovery_cases")
    reconciliation_record: Mapped["ReconciliationRecord | None"] = relationship(back_populates="recovery_cases")
