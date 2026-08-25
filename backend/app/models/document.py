from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True, default=1)
    recovery_case_id: Mapped[int | None] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(100))
    reference: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
