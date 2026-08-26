from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict


class RevenueExceptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int  # RecoveryCase ID
    merchant_id: int
    exception_type: str  # chargeback_dispute | settlement_failure | settlement_hold | reconciliation_variance | settlement_risk
    source_entity: str  # dispute | settlement | reconciliation | transaction
    source_id: str  # razorpay dispute ID, settlement ID, or reference
    amount_at_risk: Decimal
    currency: str
    priority: str  # CRITICAL | HIGH | MEDIUM | LOW
    status: str  # detected | action_required | in_progress | waiting_external | resolved | lost | closed
    provider_status: str  # raw provider status (e.g. open, under_review, failed, processed, etc.)
    deadline: datetime | None = None
    deadline_status: str = "unknown"  # deadline_safe | deadline_approaching | deadline_critical | deadline_expired | unknown
    hours_remaining: float | None = None
    reason: str
    recommended_action: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class RevenueExceptionTimelineEvent(BaseModel):
    event: str
    timestamp: datetime
    description: str
    source: str = "system"


class RevenueExceptionDetail(RevenueExceptionRead):
    description: str
    customer_id: str | None = None
    order_id: str | None = None
    payment_id: str | None = None
    utr: str | None = None
    evidence_completeness: str | None = None
    contest_summary: str | None = None
    ai_explanation: str | None = None
    timeline: list[RevenueExceptionTimelineEvent] = []


class RevenueExceptionMetrics(BaseModel):
    total_exceptions: int
    total_amount_at_risk: Decimal
    critical_count: int
    high_count: int
    action_required_count: int
    dispute_amount_at_risk: Decimal
    settlement_amount_at_risk: Decimal
    reconciliation_amount_at_risk: Decimal
    amount_recovered: Decimal
    amount_lost: Decimal
    recovery_rate: Decimal  # recovered / (recovered + lost)
    currency: str = "INR"

