from pydantic import BaseModel


class MonitorStatsResponse(BaseModel):
    total_checks: int
    successful_checks: int
    failed_checks: int
    uptime_percentage: float | None
    average_response_time_ms: float | None