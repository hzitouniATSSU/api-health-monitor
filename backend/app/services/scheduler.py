import asyncio
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models.monitor import Monitor
from app.services.monitoring import run_check


logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300


async def run_monitoring_cycle() -> None:
    with SessionLocal() as db:
        monitors = list(
            db.scalars(
                select(Monitor).order_by(Monitor.id)
            ).all()
        )

        logger.info(
            "Starting monitoring cycle: %s monitor(s)",
            len(monitors),
        )

        for monitor in monitors:
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
            CHECK_INTERVAL_SECONDS,
        )


        await asyncio.sleep(CHECK_INTERVAL_SECONDS)