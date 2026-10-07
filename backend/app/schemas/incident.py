from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    started_at: datetime
    resolved_at: datetime | None