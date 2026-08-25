from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class DashboardSummary(BaseModel):
    total_transactions: int
    high_value_transactions: int
    at_risk_transactions: int
    total_revenue_at_risk: Decimal
    high_priority_cases: int
    average_recovery_probability: Decimal
    recovered_revenue: Decimal = Decimal("0.00")
    recovery_rate: Decimal = Decimal("0.00")
    cases_awaiting_customer: int = 0
    cases_awaiting_merchant_review: int = 0
    settlement_ready_cases: int = 0


class CaseAnalysisRead(BaseModel):
    case_id: int
    transaction: dict[str, Any]
    is_high_value: bool
    risk_score: Decimal
    readiness_status: str
    risk_reasons: list[str]
    missing_information: list[str]
    revenue_at_risk: Decimal
    recovery_probability: Decimal
    next_best_action: str
    action_reason: str
    case_status: str
    analyzed_at: datetime


class ResolutionRequestResponse(BaseModel):
    case_id: int
    requested_information: list[str]
    requested_document_type: str | None = None
    customer_message: str
    status: str
    created_at: datetime


class CustomerResolveRequest(BaseModel):
    customer_name: str | None = None
    customer_email: str | None = None
    country_code: str | None = None
    invoice_amount: Decimal | None = None
    invoice_currency: str | None = None
    invoice_reference: str | None = None
    invoice_date: str | None = None
    notes: str | None = None


class ValidationCheckRead(BaseModel):
    name: str
    status: str
    message: str


class ValidationResponse(BaseModel):
    case_id: int
    status: str
    checks: list[ValidationCheckRead]
    overall_reason: str
    validated_at: datetime


class MerchantReviewRequest(BaseModel):
    decision: str
    notes: str | None = None


class MerchantReviewResponse(BaseModel):
    case_id: int
    decision: str
    case_status: str
    case_stage: str
    notes: str | None = None
    reviewed_at: datetime


class AuditLogRead(BaseModel):
    id: int
    entity_type: str
    entity_id: str
    event_type: str
    details: str | None = None
    created_at: datetime


class CaseResolutionDetails(BaseModel):
    case_id: int
    case_status: str
    case_stage: str
    next_best_action: str | None = None
    requested_information: list[str] = Field(default_factory=list)
    requested_document_type: str | None = None
    customer_message: str | None = None
    customer_submission: dict[str, Any] | None = None
    documents: list[dict[str, Any]] = Field(default_factory=list)
    latest_validation: dict[str, Any] | None = None
    merchant_decision: dict[str, Any] | None = None

