from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.merchant import Merchant
    from app.models.recovery_case import RecoveryCase
    from app.models.transaction import Transaction


class Dispute(Base):
    __tablename__ = "disputes"
    __table_args__ = (
        UniqueConstraint("merchant_id", "razorpay_dispute_id", name="uq_merchant_razorpay_dispute_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True, default=1)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True, nullable=True)
    razorpay_dispute_id: Mapped[str] = mapped_column(String(100), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    phase: Mapped[str | None] = mapped_column(String(50), default="chargeback", nullable=True)
    respond_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deducted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Production Phase 3 Workflow additions
    priority: Mapped[str] = mapped_column(String(50), default="MEDIUM", index=True)
    deadline_status: Mapped[str] = mapped_column(String(50), default="unknown", index=True)
    contest_status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    contest_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    contest_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_completeness: Mapped[str] = mapped_column(String(50), default="incomplete", index=True)
    validation_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    validation_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    merchant: Mapped["Merchant"] = relationship()
    transaction: Mapped["Transaction | None"] = relationship()
    recovery_cases: Mapped[list["RecoveryCase"]] = relationship(back_populates="dispute")
    documents: Mapped[list["Document"]] = relationship(back_populates="dispute")
