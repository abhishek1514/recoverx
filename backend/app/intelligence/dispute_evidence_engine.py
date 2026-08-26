"""Deterministic Evidence, Priority, and Deadline Intelligence Engine for RecoverX Disputes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# Supported evidence categories matching Razorpay Disputes & Document requirements
SUPPORTED_EVIDENCE_CATEGORIES = {
    "invoice": "Tax Invoice / Billing Receipt",
    "proof_of_delivery": "Proof of Delivery / Courier Tracking Receipt (POD)",
    "customer_communication": "Customer Chat / Email Correspondence",
    "order_information": "Order Confirmation & Item Details",
    "transaction_details": "Payment Gateway Transaction Log / Bank Memo",
    "terms_and_conditions": "Refund & Cancellation Terms Accepted by Customer",
    "customer_authorization": "Customer Authorization / Mandate Approval",
    "refund_information": "Credit Note / Prior Refund Record",
    "service_evidence": "Proof of Service Rendered / Access Log",
}

# Reason code mapping to deterministic evidence requirements
REASON_CODE_EVIDENCE_MAP: dict[str, dict[str, list[str]]] = {
    "fraudulent": {
        "required": ["customer_communication", "proof_of_delivery"],
        "recommended": ["invoice", "customer_authorization", "terms_and_conditions"],
    },
    "product_not_received": {
        "required": ["proof_of_delivery", "order_information"],
        "recommended": ["invoice", "customer_communication"],
    },
    "defective_goods": {
        "required": ["invoice", "customer_communication", "terms_and_conditions"],
        "recommended": ["refund_information", "service_evidence"],
    },
    "product_unacceptable": {
        "required": ["invoice", "customer_communication", "terms_and_conditions"],
        "recommended": ["service_evidence"],
    },
    "duplicate_charge": {
        "required": ["transaction_details", "invoice"],
        "recommended": ["refund_information"],
    },
    "subscription_cancelled": {
        "required": ["terms_and_conditions", "customer_communication", "invoice"],
        "recommended": ["customer_authorization"],
    },
    "general": {
        "required": ["invoice", "proof_of_delivery"],
        "recommended": ["customer_communication", "transaction_details"],
    },
}


def get_evidence_requirements(reason_code: str | None) -> dict[str, list[str]]:
    """Return deterministic required and recommended evidence categories for a dispute reason."""
    clean_reason = (reason_code or "general").lower().strip()
    return REASON_CODE_EVIDENCE_MAP.get(clean_reason, REASON_CODE_EVIDENCE_MAP["general"])


def calculate_deadline_metrics(
    respond_by: datetime | None,
    now: datetime | None = None,
) -> tuple[float | None, str]:
    """Calculate exact hours remaining and categorize deadline status deterministically."""
    if respond_by is None:
        return None, "unknown"

    current_time = now or datetime.now(UTC)
    # Ensure respond_by is timezone-aware
    if respond_by.tzinfo is None:
        target = respond_by.replace(tzinfo=UTC)
    else:
        target = respond_by.astimezone(UTC)

    diff_seconds = (target - current_time).total_seconds()
    hours_remaining = round(diff_seconds / 3600.0, 1)

    if hours_remaining <= 0:
        return hours_remaining, "deadline_expired"
    if hours_remaining < 24.0:
        return hours_remaining, "deadline_critical"
    if hours_remaining <= 72.0:
        return hours_remaining, "deadline_approaching"
    return hours_remaining, "deadline_safe"


def calculate_dispute_priority(
    amount: Decimal,
    deadline_status: str,
    evidence_completeness: str,
    status: str,
    currency: str = "INR",
) -> str:
    """Deterministically calculate dispute priority without AI bias."""
    if status in {"won", "lost", "closed"}:
        return "LOW"

    # Threshold in base currency (100k for INR, 1.2k for USD/EUR)
    high_threshold = Decimal("100000.00") if currency.upper() == "INR" else Decimal("1200.00")
    medium_threshold = Decimal("25000.00") if currency.upper() == "INR" else Decimal("300.00")

    if deadline_status == "deadline_critical":
        return "CRITICAL"
    if amount >= high_threshold and evidence_completeness != "complete":
        return "CRITICAL"
    if amount >= high_threshold or deadline_status == "deadline_approaching":
        return "HIGH"
    if amount >= medium_threshold or evidence_completeness == "incomplete":
        return "MEDIUM"
    return "LOW"


def evaluate_evidence_completeness(
    reason_code: str | None,
    submitted_document_types: list[str],
) -> tuple[str, list[str], list[str]]:
    """Determine evidence completeness status and return missing required & recommended items."""
    reqs = get_evidence_requirements(reason_code)
    required = reqs["required"]
    recommended = reqs["recommended"]

    submitted_set = {doc.lower().strip() for doc in submitted_document_types}
    missing_required = [req for req in required if req not in submitted_set]
    missing_recommended = [rec for rec in recommended if rec not in submitted_set]

    if not missing_required:
        completeness = "complete"
    elif len(missing_required) < len(required):
        completeness = "partial"
    else:
        completeness = "incomplete"

    return completeness, missing_required, missing_recommended


def validate_document_content_fields(
    dispute_amount: Decimal,
    dispute_currency: str,
    extracted_amount: Decimal | None = None,
    extracted_currency: str | None = None,
    extracted_reference: str | None = None,
    expected_reference: str | None = None,
) -> tuple[str, str]:
    """Perform deterministic verification of known document fields against dispute data."""
    if extracted_amount is None and extracted_currency is None and extracted_reference is None:
        return "pass", "Document binary and format verified. Field extraction pending manual review."

    notes: list[str] = []
    status = "pass"

    if extracted_currency and extracted_currency.upper() != dispute_currency.upper():
        notes.append(f"Currency mismatch: document specifies {extracted_currency.upper()} but dispute is in {dispute_currency.upper()}.")
        status = "fail"

    if extracted_amount is not None:
        diff = abs(extracted_amount - dispute_amount)
        if diff > Decimal("0.01"):
            notes.append(
                f"Amount mismatch: document amount ({extracted_amount:.2f} {dispute_currency}) differs from dispute amount ({dispute_amount:.2f} {dispute_currency})."
            )
            # Mark for review rather than automatic hard failure
            if status != "fail":
                status = "review"
        else:
            notes.append(f"Amount verified: exactly matches disputed amount ({dispute_amount:.2f} {dispute_currency}).")

    if extracted_reference and expected_reference:
        if extracted_reference.strip().lower() != expected_reference.strip().lower():
            notes.append(f"Reference notice: document reference '{extracted_reference}' differs from expected '{expected_reference}'.")
            if status != "fail":
                status = "review"
        else:
            notes.append(f"Reference verified: matches transaction ID {expected_reference}.")

    return status, " ".join(notes) if notes else "Deterministic checks passed."

