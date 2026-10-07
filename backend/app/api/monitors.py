from typing import Annotated

from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.monitor import Monitor
from app.schemas.monitor import MonitorCreate, MonitorResponse
from app.schemas.check import CheckResponse
from app.models.check import Check
from app.schemas.stats import MonitorStatsResponse
from app.models.incident import Incident
from app.schemas.incident import IncidentResponse

from app.services.monitoring import run_check


router = APIRouter(
    prefix="/api/monitors",
    tags=["monitors"],
)

DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=MonitorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_monitor(
    payload: MonitorCreate,
    db: DbSession,
) -> Monitor:
    monitor = Monitor(
        name=payload.name,
        url=str(payload.url),
    )

    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    return monitor


@router.get("", response_model=list[MonitorResponse])
def list_monitors(db: DbSession) -> list[Monitor]:
    statement = select(Monitor).order_by(Monitor.created_at.desc())

    return list(db.scalars(statement).all())

@router.post(
    "/{monitor_id}/check",
    response_model=CheckResponse,
)
async def check_monitor(
    monitor_id: int,
    db: DbSession,
) -> CheckResponse:
    monitor = db.get(Monitor, monitor_id)

    if monitor is None:
        raise HTTPException(
            status_code=404,
            detail="Monitor not found",
        )

    check = await run_check(db, monitor)

    return CheckResponse.model_validate(check)

@router.get(
    "/{monitor_id}/checks",
    response_model=list[CheckResponse],
)
def list_monitor_checks(
    monitor_id: int,
    db: DbSession,
    limit: int = 100,
) -> list[Check]:
    monitor = db.get(Monitor, monitor_id)

    if monitor is None:
        raise HTTPException(
            status_code=404,
            detail="Monitor not found",
        )

    statement = (
        select(Check)
        .where(Check.monitor_id == monitor_id)
        .order_by(Check.checked_at.desc())
        .limit(min(max(limit, 1), 500))
    )

    return list(db.scalars(statement).all())

@router.get(
    "/{monitor_id}/stats",
    response_model=MonitorStatsResponse,
)
def get_monitor_stats(
    monitor_id: int,
    db: DbSession,
) -> MonitorStatsResponse:
    monitor = db.get(Monitor, monitor_id)

    if monitor is None:
        raise HTTPException(
            status_code=404,
            detail="Monitor not found",
        )

    total_checks = db.scalar(
        select(func.count(Check.id))
        .where(Check.monitor_id == monitor_id)
    ) or 0

    successful_checks = db.scalar(
        select(func.count(Check.id))
        .where(
            Check.monitor_id == monitor_id,
            Check.success.is_(True),
        )
    ) or 0

    failed_checks = total_checks - successful_checks

    average_response_time = db.scalar(
        select(func.avg(Check.response_time_ms))
        .where(
            Check.monitor_id == monitor_id,
            Check.response_time_ms.is_not(None),
        )
    )

    uptime_percentage = (
        round((successful_checks / total_checks) * 100, 2)
        if total_checks
        else None
    )

    return MonitorStatsResponse(
        total_checks=total_checks,
        successful_checks=successful_checks,
        failed_checks=failed_checks,
        uptime_percentage=uptime_percentage,
        average_response_time_ms=(
            round(float(average_response_time), 2)
            if average_response_time is not None
            else None
        ),
    )


@router.delete(
    "/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_monitor(
    monitor_id: int,
    db: DbSession,
) -> None:
    monitor = db.get(Monitor, monitor_id)

    if monitor is None:
        raise HTTPException(
            status_code=404,
            detail="Monitor not found",
        )

    db.delete(monitor)
    db.commit()

@router.get(
    "/{monitor_id}/incidents",
    response_model=list[IncidentResponse],
)
def list_monitor_incidents(
    monitor_id: int,
    db: DbSession,
    limit: int = 100,
) -> list[Incident]:
    monitor = db.get(Monitor, monitor_id)

    if monitor is None:
        raise HTTPException(
            status_code=404,
            detail="Monitor not found",
        )

    statement = (
        select(Incident)
        .where(Incident.monitor_id == monitor_id)
        .order_by(Incident.started_at.desc())
        .limit(min(max(limit, 1), 500))
    )

    return list(db.scalars(statement).all())