from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RiskAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    settlement_risk_score: Decimal | None
    revenue_at_risk: Decimal | None
    recovery_probability: Decimal | None
    status: str
    rationale: str | None
    created_at: datetime
