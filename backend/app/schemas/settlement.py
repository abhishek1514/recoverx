from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict


class SettlementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    razorpay_settlement_id: str
    utr: str | None = None
    amount: Decimal
    fees: Decimal
    tax: Decimal
    currency: str
    status: str
    settled_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class SettlementExceptionRead(BaseModel):
    id: int
    razorpay_settlement_id: str
    amount: Decimal
    currency: str
    status: str
    failure_reason: str | None = None
    recommended_action: str
    created_at: datetime


class ReconciliationRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    transaction_id: int | None = None
    settlement_id: int | None = None
    expected_amount: Decimal
    settled_amount: Decimal
    fee_amount: Decimal
    tax_amount: Decimal
    adjustment_amount: Decimal
    refund_amount: Decimal
    discrepancy_amount: Decimal
    discrepancy_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class SettlementSyncResponse(BaseModel):
    status: str
    total_synced: int
    exceptions_detected: int
    timestamp: str


class SettlementMetricsResponse(BaseModel):
    total_settled_amount: str
    amount_failed: str
    amount_on_hold: str
    unexplained_reconciliation_variance: str
    failed_settlement_count: int
    on_hold_settlement_count: int
    processed_settlement_count: int
    unexplained_reconciliation_count: int
    currency: str = "INR"
