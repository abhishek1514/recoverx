from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AIExplanation(BaseModel):
    """Validated explanatory output. It contains no authority to alter policy."""

    model_config = ConfigDict(extra="forbid")
    risk_explanation: str = Field(min_length=1, max_length=2000)
    recovery_explanation: str = Field(min_length=1, max_length=2000)
    recommended_action_explanation: str = Field(min_length=1, max_length=2000)
    merchant_message: str = Field(min_length=1, max_length=2000)
    customer_message: str = Field(min_length=1, max_length=2000)
    confidence: Decimal = Field(ge=0, le=1)


class CaseAIAnalysisResponse(BaseModel):
    case_id: int
    risk_score: Decimal
    revenue_at_risk: Decimal
    recovery_probability: Decimal
    next_best_action: str
    ai_status: str
    ai: AIExplanation | None
