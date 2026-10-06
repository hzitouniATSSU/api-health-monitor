from fastapi import FastAPI

from app.api.monitors import router as monitors_router

app = FastAPI(
    title="API Health Monitor",
    version="0.1.0",
)

app.include_router(monitors_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

