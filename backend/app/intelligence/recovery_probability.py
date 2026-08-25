from __future__ import annotations

from decimal import Decimal
from typing import Any


def estimate_recovery_probability(
    transaction: Any, customer: Any | None, has_document: bool, readiness: dict[str, Any]
) -> dict[str, Any]:
    """Explainable MVP heuristic, not a production-trained ML model."""
    probability = Decimal("0.55")
    reasons: list[str] = ["MVP deterministic recovery heuristic."]
    if customer is not None:
        probability += Decimal("0.10")
        reasons.append("An existing customer record supports resolution.")
    if has_document:
        probability += Decimal("0.15")
        reasons.append("An available document supports follow-up.")
    if transaction.status in {"captured", "authorized", "received"}:
        probability += Decimal("0.05")
        reasons.append("Payment is in a normal received/authorized state.")
    if readiness["risk_score"] < 30:
        probability += Decimal("0.05")
    if readiness["is_high_value"]:
        probability += Decimal("0.05")
        reasons.append("High-value transactions are prioritized for recovery follow-up.")
    unresolved = len(readiness["missing_information"])
    if unresolved:
        probability -= Decimal("0.08") * unresolved
        reasons.append(f"{unresolved} unresolved information requirement(s) reduce certainty.")
    return {"recovery_probability": max(Decimal("0.05"), min(Decimal("0.95"), probability)), "reasons": reasons}
