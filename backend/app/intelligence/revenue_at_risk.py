from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def calculate_revenue_at_risk(amount: Decimal, risk_score: Decimal, is_high_value: bool) -> dict[str, Any]:
    """Deterministic currency arithmetic; no LLM or floating point is used."""
    risk_probability = Decimal(risk_score) / Decimal("100")
    revenue_at_risk = (Decimal(amount) * risk_probability).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if is_high_value and risk_probability >= Decimal("0.30"):
        priority = "HIGH"
    elif risk_probability >= Decimal("0.30") or is_high_value:
        priority = "MEDIUM"
    else:
        priority = "LOW"
    return {
        "transaction_amount": Decimal(amount), "risk_probability": risk_probability,
        "revenue_at_risk": revenue_at_risk, "priority": priority,
    }
