import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import engine
from app.api.monitors import router as monitors_router
from app.schemas.health import (
    WorkerHealth,
    WorkerHealthResponse,
    WorkerStatus,
)
from app.services.heartbeat import read_worker_health


logger = logging.getLogger(__name__)

# PostgreSQL SQLSTATE for "relation does not exist".
UNDEFINED_TABLE = "42P01"

app = FastAPI(
    title="API Health Monitor",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    origin.strip()
    for origin in settings.cors_origins.split(",")
    if origin.strip()
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(monitors_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Readiness check failed: database unreachable")

        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "unreachable"},
        )

    return JSONResponse(content={"status": "ok", "database": "ok"})


def _worker_health_response(
    database: str,
    worker: WorkerHealth,
) -> JSONResponse:
    healthy = database == "ok" and worker.status in (
        WorkerStatus.HEALTHY,
        WorkerStatus.STARTING,
    )

    body = WorkerHealthResponse(
        status="ok" if healthy else "unavailable",
        database=database,
        worker=worker,
    )

    return JSONResponse(
        status_code=200 if healthy else 503,
        content=body.model_dump(mode="json"),
    )


# Separate from /health/ready on purpose: the container healthcheck uses
# readiness, and a stale worker must not mark the API unhealthy.
@app.get(
    "/health/worker",
    response_model=WorkerHealthResponse,
    responses={503: {"model": WorkerHealthResponse}},
)
def worker_health() -> JSONResponse:
    stale_after_seconds = settings.worker_heartbeat_stale_seconds

    try:
        with engine.connect() as connection:
            worker = read_worker_health(connection, stale_after_seconds)
    except SQLAlchemyError as exc:
        driver_error = getattr(exc, "orig", None)

        if getattr(driver_error, "sqlstate", None) == UNDEFINED_TABLE:
            logger.error(
                "Worker health check failed: worker_heartbeats table "
                "is missing; database migrations have not been applied"
            )

            return _worker_health_response(
                "ok",
                WorkerHealth(
                    status=WorkerStatus.UNKNOWN,
                    detail=(
                        "Heartbeat table not found; apply database "
                        "migrations (alembic upgrade head)."
                    ),
                    stale_after_seconds=stale_after_seconds,
                ),
            )

        logger.exception("Worker health check failed: database unreachable")

        return _worker_health_response(
            "unreachable",
            WorkerHealth(
                status=WorkerStatus.UNKNOWN,
                detail="Database unreachable; worker health cannot be determined.",
                stale_after_seconds=stale_after_seconds,
            ),
        )

    if worker.status not in (WorkerStatus.HEALTHY, WorkerStatus.STARTING):
        logger.warning(
            "Worker health check: status=%s detail=%s",
            worker.status,
            worker.detail,
        )

    return _worker_health_response("ok", worker)
