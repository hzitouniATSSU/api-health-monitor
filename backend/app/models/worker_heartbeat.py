from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkerHeartbeat(Base):
    """Latest liveness and progress report from a background worker.

    One row per worker role. Every timestamp is written with the database
    clock (now()) so that staleness can be computed without trusting the
    clocks of the worker or API containers.
    """

    __tablename__ = "worker_heartbeats"

    worker_name: Mapped[str] = mapped_column(String(50), primary_key=True)

    # Identifies the running process; a new value means the worker restarted.
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    last_cycle_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_cycle_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_cycle_duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    last_cycle_monitor_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
