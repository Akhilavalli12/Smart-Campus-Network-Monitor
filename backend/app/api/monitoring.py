"""Read endpoints for monitoring results, plus runtime configuration.

Nothing here sends a probe: the monitoring engine does that on its own schedule and
these routes only read what it stored.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.dependencies import get_engine, get_monitoring_store, get_store
from app.config import Settings, get_settings
from app.monitoring.engine import MonitoringEngine, config_from_settings
from app.monitoring.history import HistoryPoint, history_points
from app.monitoring.models import Measurement, MonitoringConfig, StatusEvent
from app.monitoring.store import MonitoringStore
from app.network_model import service as network_service
from app.network_model.store import NetworkStore

router = APIRouter(tags=["monitoring"])


class EngineStatusOut(BaseModel):
    enabled: bool
    running: bool = False
    cycles_completed: int = 0
    last_cycle_at: datetime | None = None
    last_cycle_duration_ms: float | None = None
    last_error: str | None = None
    poll_interval_s: float | None = None
    failure_confirmations: int | None = None
    detection_time_s: float | None = None  # worst-case time to declare a device OFFLINE


class ConfigOut(BaseModel):
    config: MonitoringConfig
    source: str  # "stored" or "defaults"


@router.get("/monitoring/status", response_model=EngineStatusOut)
async def engine_status(
    engine: MonitoringEngine | None = Depends(get_engine),
    store: MonitoringStore = Depends(get_monitoring_store),
    settings: Settings = Depends(get_settings),
) -> EngineStatusOut:
    if engine is None:
        return EngineStatusOut(enabled=False)
    config = await store.get_config() or config_from_settings(settings)
    status = engine.status
    return EngineStatusOut(
        enabled=True,
        running=status.running,
        cycles_completed=status.cycles_completed,
        last_cycle_at=status.last_cycle_at,
        last_cycle_duration_ms=status.last_cycle_duration_ms,
        last_error=status.last_error,
        poll_interval_s=config.poll_interval_s,
        failure_confirmations=config.failure_confirmations,
        detection_time_s=config.poll_interval_s * config.failure_confirmations,
    )


@router.get("/monitoring/config", response_model=ConfigOut)
async def get_config(store: MonitoringStore = Depends(get_monitoring_store), settings: Settings = Depends(get_settings)) -> ConfigOut:
    stored = await store.get_config()
    return ConfigOut(config=stored or config_from_settings(settings), source="stored" if stored else "defaults")


@router.put("/monitoring/config", response_model=ConfigOut)
async def put_config(config: MonitoringConfig, store: MonitoringStore = Depends(get_monitoring_store)) -> ConfigOut:
    """Replace the runtime configuration. The engine reads it at the start of every cycle."""
    await store.save_config(config)
    return ConfigOut(config=config, source="stored")


@router.get("/devices/{device_id}/measurements", response_model=list[Measurement])
async def device_measurements(
    device_id: str,
    hours: float = Query(1.0, gt=0, le=48),
    limit: int = Query(500, ge=1, le=5000),
    network: NetworkStore = Depends(get_store),
    store: MonitoringStore = Depends(get_monitoring_store),
) -> list[Measurement]:
    """Probe history for one device, oldest first (ready for a time-series chart)."""
    await network_service.get_device_or_404(network, device_id)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return await store.list_measurements(device_id, since=since, limit=limit)


@router.get("/devices/{device_id}/history", response_model=list[HistoryPoint])
async def device_history(
    device_id: str,
    hours: float = Query(1.0, gt=0, le=48),
    bucket_s: int = Query(0, ge=0, le=3600, description="average into buckets of this many seconds (0 = raw)"),
    limit: int = Query(5000, ge=1, le=20000),
    network: NetworkStore = Depends(get_store),
    store: MonitoringStore = Depends(get_monitoring_store),
) -> list[HistoryPoint]:
    """Chart-ready latency / loss / jitter history of one device."""
    await network_service.get_device_or_404(network, device_id)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return history_points(await store.list_measurements(device_id, since=since, limit=limit), bucket_s)


@router.get("/events", response_model=list[StatusEvent])
async def list_events(
    limit: int = Query(50, ge=1, le=500),
    device_id: str | None = None,
    store: MonitoringStore = Depends(get_monitoring_store),
) -> list[StatusEvent]:
    """Status changes, newest first."""
    return await store.list_events(limit=limit, device_id=device_id)
