from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class DisputeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    transaction_id: int | None = None
    razorpay_dispute_id: str
    payment_id: str | None = None
    amount: Decimal
    currency: str
    reason_code: str | None = None
    status: str
    phase: str | None = None
    respond_by: datetime | None = None
    deducted_at: datetime | None = None
    evidence_submitted_at: datetime | None = None

    priority: str = "MEDIUM"
    deadline_status: str = "unknown"
    hours_remaining: float | None = None
    contest_status: str = "draft"
    contest_summary: str | None = None
    contest_submitted_at: datetime | None = None
    submission_error: str | None = None
    evidence_completeness: str = "incomplete"
    validation_status: str = "pending"
    validation_notes: str | None = None

    created_at: datetime
    updated_at: datetime


class DisputeContestRequest(BaseModel):
    summary: str = Field(..., min_length=10, max_length=2000, description="Explanation and defense summary for the dispute.")
    documents: list[str] = Field(default_factory=list, description="List of document IDs or URLs supporting the contest.")


class DisputeEvidenceItem(BaseModel):
    id: int
    document_type: str
    file_name: str | None = None
    file_size_bytes: int | None = None
    reference: str | None = None
    status: str
    created_at: datetime


class DisputeEvidenceResponse(BaseModel):
    dispute_id: int
    reason_code: str
    required_evidence: list[str]
    recommended_evidence: list[str]
    submitted_documents: list[DisputeEvidenceItem]
    evidence_completeness: str
    missing_required: list[str]
    missing_recommended: list[str]
    validation_status: str
    validation_notes: str | None = None


class DisputeContestDraftRequest(BaseModel):
    merchant_notes: str | None = Field(None, max_length=1000, description="Optional merchant operational notes.")


class DisputeContestDraftResponse(BaseModel):
    contest_summary: str
    merchant_explanation: str
    customer_communication_draft: str
    recommended_action: str
    disclaimer: str = "AI-generated draft — requires merchant review."
    is_ai_generated: bool = False


class DisputeContestApproveRequest(BaseModel):
    approved_summary: str | None = Field(None, min_length=10, max_length=2000, description="Final merchant-approved defense summary.")


class DisputeTimelineEvent(BaseModel):
    event: str
    title: str
    description: str
    timestamp: str
    status: str = "completed"


class DisputeMetricsResponse(BaseModel):
    total_disputed_amount: str
    amount_at_risk: str
    amount_contested: str
    amount_recovered: str
    amount_lost: str
    open_disputes: int
    deadline_critical_disputes: int
    evidence_complete_rate: float
    contest_success_rate: float
    currency: str = "INR"
