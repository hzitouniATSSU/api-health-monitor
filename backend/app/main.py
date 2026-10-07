from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.monitors import router as monitors_router


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