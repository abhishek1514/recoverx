"""Explainable settlement-readiness heuristic for the RecoverX MVP."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.config import get_settings


def analyze_settlement_readiness(
    transaction: Any, customer: Any | None, has_document: bool, previous_transaction_count: int = 0
) -> dict[str, Any]:
    """Score transparent operational signals; this is not a trained ML model."""
    settings = get_settings()
    score = 0
    reasons: list[str] = []
    missing: list[str] = []
    currency = getattr(transaction, "currency", "INR") or "INR"
    threshold = settings.get_high_value_threshold(currency)
    is_high_value = Decimal(transaction.amount) >= threshold

    if is_high_value:
        score += 20
        reasons.append("Transaction exceeds the configured high-value threshold.")

    if customer is None:
        score += 25
        missing.append("customer_information")
        reasons.append("No customer record is available.")
    else:
        incomplete = [field for field in ("name", "email", "country_code") if not getattr(customer, field)]
        if incomplete:
            score += 20
            missing.append("customer_information")
            reasons.append("Customer information is incomplete.")
    if not has_document:
        score += 25
        missing.append("invoice_or_document")
        reasons.append("No available invoice or supporting document is linked to this case.")
    if transaction.status not in {"captured", "authorized", "received"}:
        score += 20
        reasons.append(f"Payment status '{transaction.status}' needs review.")
    if not transaction.payment_method:
        score += 10
        missing.append("transaction_type")
        reasons.append("Payment method or transaction type is unavailable.")
    if previous_transaction_count == 0:
        score += 5
        reasons.append("No previous transaction history is available for this customer.")

    score = min(score, 100)
    readiness = "HIGH_RISK" if score >= 70 else "AT_RISK" if score >= 30 else "READY"
    confidence = max(Decimal("0.50"), Decimal("0.95") - Decimal("0.08") * len(missing))
    return {
        "risk_score": Decimal(score), "readiness_status": readiness,
        "risk_reasons": reasons, "missing_information": missing,
        "confidence": confidence, "is_high_value": is_high_value,
    }
