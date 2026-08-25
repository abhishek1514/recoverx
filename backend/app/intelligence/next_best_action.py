from __future__ import annotations

from decimal import Decimal
from typing import Any


def select_next_best_action(readiness: dict[str, Any]) -> dict[str, Any]:
    """Select a deterministic, non-financial operational follow-up."""
    missing = set(readiness["missing_information"])
    score = Decimal(readiness["risk_score"])
    if readiness["readiness_status"] == "READY":
        return {"action": "NO_ACTION", "reason": "Transaction is settlement-ready by MVP rules.", "confidence": Decimal("0.90")}
    if score >= 70:
        return {"action": "MERCHANT_REVIEW", "reason": "High or ambiguous settlement friction requires merchant review.", "confidence": Decimal("0.85")}
    if "invoice_or_document" in missing:
        return {"action": "REQUEST_DOCUMENT", "reason": "Supporting invoice or document is missing.", "confidence": Decimal("0.85")}
    if missing:
        return {"action": "REQUEST_INFORMATION", "reason": "Required customer or transaction information is incomplete.", "confidence": Decimal("0.85")}
    return {"action": "MERCHANT_REVIEW", "reason": "Settlement friction remains ambiguous.", "confidence": Decimal("0.70")}
