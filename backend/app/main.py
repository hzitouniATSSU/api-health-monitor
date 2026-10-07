from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.monitors import router as monitors_router


app = FastAPI(
    title="API Health Monitor",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(monitors_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}