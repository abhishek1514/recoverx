from datetime import datetime
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.core.currencies import is_valid_country, is_valid_currency

ALLOWED_PAYMENT_STATUSES = {"received", "captured", "authorized", "pending", "failed", "settlement_held"}


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str | None
    order_id: str | None
    customer_id: int | None
    amount: Decimal
    currency: str
    status: str
    payment_method: str | None
    event_type: str | None
    country_code: str | None
    created_at: datetime
    updated_at: datetime


class TestTransactionCreate(BaseModel):
    amount: Decimal = Field(gt=0, description="Transaction amount (must be strictly > 0)")
    currency: str = Field(min_length=3, max_length=3, default="INR", description="ISO 4217 3-letter currency code")
    country_code: str = Field(min_length=2, max_length=2, default="IN", description="ISO 3166-1 alpha-2 country code")
    payment_status: str = Field(default="received", description="Payment status")
    customer_information_complete: bool = Field(default=True, description="Whether customer profile data is complete")
    document_available: bool = Field(default=False, description="Whether an invoice/document is available")
    invoice_amount: Decimal | None = Field(default=None, ge=0, description="Submitted invoice amount if supplied")
    invoice_currency: str | None = Field(default=None, min_length=3, max_length=3, description="Invoice currency")
    invoice_reference: str | None = Field(default=None, max_length=100, description="Invoice reference identifier")
    customer_name: str | None = Field(default=None, max_length=255)
    customer_email: str | None = Field(default=None, max_length=255)

    @field_validator("currency", "invoice_currency")
    @classmethod
    def validate_currency(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v_clean = v.strip().upper()
        if not re.match(r"^[A-Z]{3}$", v_clean) or not is_valid_currency(v_clean):
            raise ValueError(f"Invalid currency '{v}'. Must be a recognized ISO 4217 code (e.g. USD, EUR, INR, GBP).")
        return v_clean

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, v: str) -> str:
        v_clean = v.strip().upper()
        if not re.match(r"^[A-Z]{2}$", v_clean) or not is_valid_country(v_clean):
            raise ValueError(f"Invalid country code '{v}'. Must be a recognized ISO 3166-1 alpha-2 code (e.g. US, IN, GB, DE).")
        return v_clean

    @field_validator("payment_status")
    @classmethod
    def validate_payment_status(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if v_clean not in ALLOWED_PAYMENT_STATUSES:
            raise ValueError(f"Invalid payment status '{v}'. Allowed: {', '.join(sorted(ALLOWED_PAYMENT_STATUSES))}")
        return v_clean


class TestTransactionResponse(BaseModel):
    transaction_id: int
    amount: Decimal
    currency: str
    country_code: str
    is_high_value: bool
    risk_score: Decimal
    readiness_status: str
    revenue_at_risk: Decimal
    recovery_probability: Decimal
    next_best_action: str
    case_id: int
    is_cross_border_mismatch: bool = False
    currency_note: str | None = None


class RazorpayOrderCreate(BaseModel):
    amount: Decimal = Field(gt=0, description="Payment amount in standard currency units (must be > 0)")
    currency: str = Field(min_length=3, max_length=3, default="INR", description="ISO 4217 3-letter currency code")
    receipt: str | None = Field(default=None, max_length=100)
    customer_name: str | None = Field(default=None, max_length=255)
    customer_email: str | None = Field(default=None, max_length=255)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        v_clean = v.strip().upper()
        if not re.match(r"^[A-Z]{3}$", v_clean) or not is_valid_currency(v_clean):
            raise ValueError(f"Invalid currency '{v}'. Must be a recognized ISO 4217 code.")
        return v_clean


class RazorpayOrderResponse(BaseModel):
    order_id: str
    amount: Decimal
    currency: str
    key_id: str
    amount_subunits: int
    receipt: str | None = None
    status: str = "created"


class RazorpayPaymentVerifyRequest(BaseModel):
    razorpay_payment_id: str = Field(min_length=1, max_length=100)
    razorpay_order_id: str = Field(min_length=1, max_length=100)
    razorpay_signature: str = Field(min_length=1, max_length=256)


class RazorpayPaymentVerifyResponse(BaseModel):
    verified: bool
    payment_id: str
    order_id: str
    status: str
    message: str


class TimelineEvent(BaseModel):
    key: str
    title: str
    description: str
    status: str  # completed, in_progress, pending, failed
    timestamp: datetime | None = None


class RazorpayOrderStatusResponse(BaseModel):
    order_id: str
    payment_id: str | None = None
    amount: Decimal
    currency: str
    status: str
    transaction_id: int | None = None
    case_id: int | None = None
    risk_score: Decimal | None = None
    revenue_at_risk: Decimal | None = None
    recovery_probability: Decimal | None = None
    next_best_action: str | None = None
    timeline: list[TimelineEvent] = Field(default_factory=list)



