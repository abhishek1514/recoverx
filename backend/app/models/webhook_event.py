from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="received", index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
