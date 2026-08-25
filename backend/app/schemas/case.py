from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RecoveryCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    customer_id: int | None
    status: str
    stage: str
    amount_at_risk: Decimal | None
    created_at: datetime
    updated_at: datetime
