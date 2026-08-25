from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.recovery_case import RecoveryCase
    from app.models.transaction import Transaction
    from app.models.user import User


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    country_code: Mapped[str] = mapped_column(String(2), default="IN")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="merchant", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="merchant")
    recovery_cases: Mapped[list["RecoveryCase"]] = relationship(back_populates="merchant")

