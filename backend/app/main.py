import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.monitors import router as monitors_router
from app.services.scheduler import scheduler_loop


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting scheduler")

    scheduler_task = asyncio.create_task(scheduler_loop())

    try:
        yield
    finally:
        logger.info("Stopping scheduler")

        scheduler_task.cancel()

        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="API Health Monitor",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(monitors_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}