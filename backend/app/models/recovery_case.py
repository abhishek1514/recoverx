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
    from app.models.transaction import Transaction


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True, default=1)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    stage: Mapped[str] = mapped_column(String(100), default="settlement_risk", index=True)
    amount_at_risk: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    recovery_probability: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    priority: Mapped[str | None] = mapped_column(String(20), index=True)
    next_best_action: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    merchant: Mapped["Merchant | None"] = relationship(back_populates="recovery_cases")
    transaction: Mapped["Transaction"] = relationship(back_populates="recovery_cases")
    customer: Mapped["Customer | None"] = relationship(back_populates="recovery_cases")
