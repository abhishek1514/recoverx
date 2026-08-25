from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    recovery_case_id: Mapped[int] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    validation_type: Mapped[str] = mapped_column(String(100))
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
