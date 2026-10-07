import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models.monitor import Monitor
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
) -> None:
    if now is None:
        now = datetime.now(timezone.utc)

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


async def scheduler_loop() -> None:
    while True:
        try:
            await run_monitoring_cycle()
        except Exception:
            logger.exception("Monitoring cycle failed")

        logger.info(
            "Monitoring cycle complete; sleeping %s seconds",
            SCHEDULER_TICK_SECONDS,
        )

        await asyncio.sleep(SCHEDULER_TICK_SECONDS)