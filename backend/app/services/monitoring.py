from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.check import Check
from app.models.monitor import Monitor
from app.services.checker import CheckResult, check_url


async def run_check(
    db: Session,
    monitor: Monitor,
) -> Check:
    result: CheckResult = await check_url(monitor.url)

    check = Check(
        monitor_id=monitor.id,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        success=result.success,
        error_type=result.error_type,
        error_message=result.error_message,
    )

    monitor.current_status = "UP" if result.success else "DOWN"
    monitor.last_checked_at = datetime.now(timezone.utc)

    db.add(check)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(check)

    return check