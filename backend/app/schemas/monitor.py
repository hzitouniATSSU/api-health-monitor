from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, HttpUrl, StringConstraints, field_validator

# Limits mirror the column sizes on Monitor so oversized input is
# rejected with a 422 instead of failing at the database.
MAX_NAME_LENGTH = 100
MAX_URL_LENGTH = 2048

MonitorName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_NAME_LENGTH,
    ),
]


class MonitorCreate(BaseModel):
    name: MonitorName
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def url_fits_column(cls, url: HttpUrl) -> HttpUrl:
        # Checked after normalization, which can lengthen the URL
        # (e.g. by inserting a "/" before the query string).
        if len(str(url)) > MAX_URL_LENGTH:
            raise ValueError(
                f"URL must be at most {MAX_URL_LENGTH} characters"
            )

        return url


class MonitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    current_status: str
    last_checked_at: datetime | None
    created_at: datetime
