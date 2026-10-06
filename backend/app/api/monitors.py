from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.monitor import Monitor
from app.schemas.monitor import MonitorCreate, MonitorResponse


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