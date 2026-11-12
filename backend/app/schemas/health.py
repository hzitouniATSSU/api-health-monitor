from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class WorkerStatus(StrEnum):
    # Heartbeat is fresh and a monitoring cycle completed since startup.
    HEALTHY = "healthy"
    # Heartbeat is fresh but this worker instance has not completed a cycle.
    STARTING = "starting"
    # No heartbeat within the staleness threshold: crashed, hung or stopped.
    STALE = "stale"
    # No worker has ever recorded a heartbeat in this database.
    MISSING = "missing"
    # Worker health could not be read (database or schema problem).
    UNKNOWN = "unknown"


class WorkerHealth(BaseModel):
    status: WorkerStatus
    detail: str
    stale_after_seconds: int
    checked_at: datetime | None = None
    heartbeat_age_seconds: float | None = None
    instance_id: str | None = None
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_cycle_started_at: datetime | None = None
    last_cycle_completed_at: datetime | None = None
    last_cycle_duration_ms: int | None = None
    last_cycle_monitor_count: int | None = None
    cycle_in_progress: bool | None = None


class WorkerHealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unreachable"]
    worker: WorkerHealth
