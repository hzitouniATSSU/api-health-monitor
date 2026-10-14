from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str

    resend_api_key: str | None = None
    alert_from_email: str | None = None
    alert_to_email: str | None = None
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Seconds without a worker heartbeat before /health/worker reports the
    # worker as stale. The floor keeps it well above the scheduler's 10s
    # idle tick so a healthy worker cannot flap. See
    # docs/WORKER_HEARTBEAT.md for how to size it.
    worker_heartbeat_stale_seconds: int = Field(default=120, ge=30)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

settings = Settings()


