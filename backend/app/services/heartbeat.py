import logging
import os
import socket
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from app.database import engine as default_engine
from app.models.worker_heartbeat import WorkerHeartbeat
from app.schemas.health import WorkerHealth, WorkerStatus

logger = logging.getLogger(__name__)

MONITORING_WORKER = "monitoring"


def new_instance_id() -> str:
    # The hostname is the container ID under Docker; the random suffix keeps
    # IDs unique even if a restarted container reuses the same PID.
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class HeartbeatWriter:
    """Records worker progress in the worker_heartbeats table.

    Writes use their own short transaction so that a heartbeat failure
    never rolls back or interrupts monitoring work, and vice versa.
    """

    def __init__(
        self,
        worker_name: str = MONITORING_WORKER,
        instance_id: str | None = None,
        engine: Engine | None = None,
    ):
        self.worker_name = worker_name
        self.instance_id = instance_id or new_instance_id()
        self._engine = engine or default_engine

    def beat(
        self,
        *,
        cycle_started: bool = False,
        cycle_completed: bool = False,
        monitor_count: int | None = None,
        cycle_duration_ms: int | None = None,
    ) -> bool:
        table = WorkerHeartbeat.__table__

        values: dict[str, Any] = {
            "worker_name": self.worker_name,
            "instance_id": self.instance_id,
            "started_at": func.now(),
            "last_heartbeat_at": func.now(),
        }

        if cycle_started:
            values["last_cycle_started_at"] = func.now()
            values["last_cycle_monitor_count"] = monitor_count

        if cycle_completed:
            values["last_cycle_completed_at"] = func.now()
            values["last_cycle_duration_ms"] = cycle_duration_ms

        statement = insert(table).values(**values)
        excluded = statement.excluded

        updates = {
            column: excluded[column]
            for column in values
            if column not in ("worker_name", "started_at")
        }

        # started_at only moves when a different process takes over the
        # row, which is how a restart is detected.
        updates["started_at"] = case(
            (table.c.instance_id != excluded.instance_id, excluded.started_at),
            else_=table.c.started_at,
        )

        statement = statement.on_conflict_do_update(
            index_elements=[table.c.worker_name],
            set_=updates,
        )

        try:
            with self._engine.begin() as connection:
                connection.execute(statement)
        except Exception:
            # Monitoring must keep running when the heartbeat cannot be
            # stored; the missing heartbeat itself becomes the signal.
            logger.warning(
                "Failed to record heartbeat for worker=%s instance=%s",
                self.worker_name,
                self.instance_id,
                exc_info=True,
            )
            return False

        return True


def evaluate_worker_health(
    heartbeat: Mapping[str, Any] | None,
    now: datetime,
    stale_after_seconds: int,
) -> WorkerHealth:
    """Classify a heartbeat row. `now` must come from the database clock."""
    if heartbeat is None:
        return WorkerHealth(
            status=WorkerStatus.MISSING,
            detail="No worker heartbeat has been recorded.",
            stale_after_seconds=stale_after_seconds,
            checked_at=now,
        )

    started_at = heartbeat["started_at"]
    cycle_started_at = heartbeat["last_cycle_started_at"]
    cycle_completed_at = heartbeat["last_cycle_completed_at"]

    # now() is the start of the reading transaction, so a heartbeat
    # committed just after it can look slightly in the future.
    age = max(
        (now - heartbeat["last_heartbeat_at"]).total_seconds(),
        0.0,
    )

    # A cycle left unfinished by a previous instance is not in progress.
    cycle_in_progress = (
        cycle_started_at is not None
        and cycle_started_at >= started_at
        and (cycle_completed_at is None or cycle_started_at > cycle_completed_at)
    )

    completed_since_start = (
        cycle_completed_at is not None and cycle_completed_at >= started_at
    )

    if age > stale_after_seconds:
        status = WorkerStatus.STALE
        detail = (
            f"No heartbeat for {age:.0f}s "
            f"(threshold {stale_after_seconds}s)."
        )
    elif not completed_since_start:
        status = WorkerStatus.STARTING
        detail = "Worker is running but has not completed a monitoring cycle yet."
    else:
        status = WorkerStatus.HEALTHY
        detail = "Worker heartbeat is fresh."

    return WorkerHealth(
        status=status,
        detail=detail,
        stale_after_seconds=stale_after_seconds,
        checked_at=now,
        heartbeat_age_seconds=round(age, 3),
        instance_id=heartbeat["instance_id"],
        started_at=started_at,
        last_heartbeat_at=heartbeat["last_heartbeat_at"],
        last_cycle_started_at=cycle_started_at,
        last_cycle_completed_at=cycle_completed_at,
        last_cycle_duration_ms=heartbeat["last_cycle_duration_ms"],
        last_cycle_monitor_count=heartbeat["last_cycle_monitor_count"],
        cycle_in_progress=cycle_in_progress,
    )


def read_worker_health(
    connection: Connection,
    stale_after_seconds: int,
    worker_name: str = MONITORING_WORKER,
) -> WorkerHealth:
    # Both statements run in one transaction, so now() is the same value
    # the heartbeat ages are measured against.
    now = connection.execute(select(func.now())).scalar_one()

    heartbeat = connection.execute(
        select(WorkerHeartbeat.__table__).where(
            WorkerHeartbeat.worker_name == worker_name
        )
    ).mappings().first()

    return evaluate_worker_health(heartbeat, now, stale_after_seconds)
