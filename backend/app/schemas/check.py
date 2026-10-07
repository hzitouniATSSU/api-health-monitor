from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    checked_at: datetime
    status_code: int | None
    response_time_ms: int | None
    success: bool
    error_type: str | None
    error_message: str | None