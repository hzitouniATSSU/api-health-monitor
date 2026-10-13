import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models.monitor import Monitor
from app.services.heartbeat import HeartbeatWriter
from app.services.monitoring import run_check


logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300
SCHEDULER_TICK_SECONDS = 10


def is_monitor_due(
    monitor: Monitor,
    now: datetime,
) -> bool:
    if monitor.last_checked_at is None:
        return True

    return (
        now - monitor.last_checked_at
        >= timedelta(seconds=CHECK_INTERVAL_SECONDS)
    )


async def run_monitoring_cycle(
    now: datetime | None = None,
    heartbeat: HeartbeatWriter | None = None,
) -> None:
    if now is None:
        now = datetime.now(timezone.utc)

    cycle_started = time.monotonic()

    with SessionLocal() as db:
        monitors = list(
            db.scalars(
                select(Monitor).order_by(Monitor.id)
            ).all()
        )

        due_monitors = [
            monitor
            for monitor in monitors
            if is_monitor_due(monitor, now)
        ]

        logger.info(
            "Monitoring cycle: %s monitor(s), %s due",
            len(monitors),
            len(due_monitors),
        )

        # Heartbeats mark progress, not just a live process: one after the
        # monitors load, one per check and one at the end. Each check has a
        # bounded deadline, so a long cycle keeps beating while a hung one
        # goes quiet.
        if heartbeat is not None:
            heartbeat.beat(
                cycle_started=True,
                monitor_count=len(monitors),
            )

        for monitor in due_monitors:
            try:
                await run_check(db, monitor)

                logger.info(
                    "Checked monitor id=%s status=%s",
                    monitor.id,
                    monitor.current_status,
                )

            except Exception:
                logger.exception(
                    "Failed to check monitor id=%s",
                    monitor.id,
                )

            if heartbeat is not None:
                heartbeat.beat()

    if heartbeat is not None:
        heartbeat.beat(
            cycle_completed=True,
            cycle_duration_ms=round(
                (time.monotonic() - cycle_started) * 1000
            ),
        )


async def scheduler_loop(
    heartbeat: HeartbeatWriter | None = None,
) -> None:
    if heartbeat is None:
        heartbeat = HeartbeatWriter()

    logger.info(
        "Worker instance %s registering heartbeat",
        heartbeat.instance_id,
    )

    # Register before any work so a restart is visible as "starting"
    # immediately instead of looking stale until the first cycle ends.
    heartbeat.beat()

    while True:
        try:
            await run_monitoring_cycle(heartbeat=heartbeat)
        except Exception:
            logger.exception("Monitoring cycle failed")

        logger.info(
            "Monitoring cycle complete; sleeping %s seconds",
            SCHEDULER_TICK_SECONDS,
        )

        await asyncio.sleep(SCHEDULER_TICK_SECONDS)