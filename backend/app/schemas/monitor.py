from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl


class MonitorCreate(BaseModel):
    name: str
    url: HttpUrl


class MonitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    current_status: str
    last_checked_at: datetime | None
    created_at: datetime