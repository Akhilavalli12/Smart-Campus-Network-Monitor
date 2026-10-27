import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_mongo
from app.config import get_settings
from app.db import MongoManager

router = APIRouter(tags=["health"])

_PROCESS_STARTED = time.monotonic()


class DatabaseHealth(BaseModel):
    status: Literal["up", "down"]
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    server_time: datetime
    uptime_seconds: float
    database: DatabaseHealth


@router.get("/health", response_model=HealthResponse)
async def health(mongo: MongoManager = Depends(get_mongo)) -> HealthResponse:
    """Liveness + dependency check.

    Always answers HTTP 200 while the API process is alive; `status` becomes
    "degraded" when MongoDB cannot be reached.
    """
    settings = get_settings()
    db_status = await mongo.ping()
    return HealthResponse(
        status="ok" if db_status.reachable else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        server_time=datetime.now(timezone.utc),
        uptime_seconds=round(time.monotonic() - _PROCESS_STARTED, 1),
        database=DatabaseHealth(
            status="up" if db_status.reachable else "down",
            latency_ms=db_status.latency_ms,
            error=db_status.error,
        ),
    )
