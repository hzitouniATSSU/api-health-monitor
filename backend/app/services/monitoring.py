from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.check import Check
from app.models.incident import Incident
from app.models.monitor import Monitor
from app.services.checker import CheckResult, check_url


async def run_check(db: Session, monitor: Monitor) -> Check:
    result: CheckResult = await check_url(monitor.url)

    previous_status = monitor.current_status
    new_status = "UP" if result.success else "DOWN"
    now = datetime.now(timezone.utc)

    check = Check(
        monitor_id=monitor.id,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        success=result.success,
        error_type=result.error_type,
        error_message=result.error_message,
    )

    # A new outage has begun.
    if new_status == "DOWN" and previous_status != "DOWN":
        db.add(
            Incident(
                monitor_id=monitor.id,
                started_at=now,
            )
        )

    # An existing outage has recovered.
    elif new_status == "UP" and previous_status == "DOWN":
        open_incident = db.scalar(
            select(Incident)
            .where(
                Incident.monitor_id == monitor.id,
                Incident.resolved_at.is_(None),
            )
            .order_by(Incident.started_at.desc())
            .limit(1)
        )

        if open_incident is not None:
            open_incident.resolved_at = now

    monitor.current_status = new_status
    monitor.last_checked_at = now

    db.add(check)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(check)

    return check