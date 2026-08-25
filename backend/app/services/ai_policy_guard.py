"""Policy guard: AI language can explain decisions but cannot change them."""

from __future__ import annotations

from decimal import Decimal

from app.ai.schemas import AIExplanation


def apply_policy_guard(
    ai: AIExplanation, *, risk_score: Decimal, revenue_at_risk: Decimal,
    recovery_probability: Decimal, deterministic_action: str, suggested_action: str | None = None,
) -> dict[str, object]:
    """Return deterministic values unchanged, regardless of AI recommendation."""
    return {
        "ai": ai, "risk_score": risk_score, "revenue_at_risk": revenue_at_risk,
        "recovery_probability": recovery_probability, "next_best_action": deterministic_action,
        "action_overridden": bool(suggested_action and suggested_action != deterministic_action),
    }
