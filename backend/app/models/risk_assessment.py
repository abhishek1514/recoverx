from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.transaction import Transaction


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    settlement_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    readiness_status: Mapped[str | None] = mapped_column(String(50), index=True)
    risk_reasons: Mapped[str | None] = mapped_column(Text)
    missing_information: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    revenue_at_risk: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    recovery_probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transaction: Mapped["Transaction"] = relationship(back_populates="risk_assessments")
