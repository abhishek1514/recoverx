from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.dispute import Dispute
    from app.models.merchant import Merchant
    from app.models.recovery_case import RecoveryCase


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True, default=1)
    recovery_case_id: Mapped[int | None] = mapped_column(ForeignKey("recovery_cases.id"), index=True, nullable=True)
    dispute_id: Mapped[int | None] = mapped_column(ForeignKey("disputes.id"), index=True, nullable=True)
    document_type: Mapped[str] = mapped_column(String(100))
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    merchant: Mapped["Merchant | None"] = relationship()
    recovery_case: Mapped["RecoveryCase | None"] = relationship()
    dispute: Mapped["Dispute | None"] = relationship(back_populates="documents")
