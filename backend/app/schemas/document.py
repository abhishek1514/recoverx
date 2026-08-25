from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recovery_case_id: int | None
    document_type: str
    reference: str | None
    status: str
    created_at: datetime
