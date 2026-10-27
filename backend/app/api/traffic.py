"""Read endpoints for traffic. Nothing here reads a counter: the traffic engine does that on its own schedule."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.dependencies import get_monitoring_store, get_store, get_traffic_engine, get_traffic_store
from app.config import Settings, get_settings
from app.monitoring.engine import config_from_settings
from app.monitoring.store import MonitoringStore
from app.network_model import service as network_service
from app.network_model.errors import NotFoundError
from app.network_model.store import NetworkStore
from app.traffic import aggregate
from app.traffic.engine import TrafficEngine
from app.traffic.models import BlockSeriesPoint, LinkTraffic, ProtocolDistribution, SeriesPoint, TrafficSummary
from app.traffic.store import TrafficStore

router = APIRouter(prefix="/traffic", tags=["traffic"])


class TrafficStatus(BaseModel):
    enabled: bool
    running: bool = False
    cycles_completed: int = 0
    last_cycle_at: datetime | None = None
    last_cycle_duration_ms: float | None = None
    last_error: str | None = None
    interval_s: float | None = None
    host_label: str | None = None
    host_error: str | None = None
    counter_bits: int | None = None


async def _thresholds(monitoring: MonitoringStore, settings: Settings):
    return (await monitoring.get_config() or config_from_settings(settings)).thresholds


@router.get("/status", response_model=TrafficStatus)
async def traffic_status(engine: TrafficEngine | None = Depends(get_traffic_engine), settings: Settings = Depends(get_settings)) -> TrafficStatus:
    if engine is None:
        return TrafficStatus(enabled=False)
    s = engine.status
    return TrafficStatus(enabled=True, running=s.running, cycles_completed=s.cycles_completed, last_cycle_at=s.last_cycle_at,
                         last_cycle_duration_ms=s.last_cycle_duration_ms, last_error=s.last_error, interval_s=settings.traffic_interval_s,
                         host_label=engine.host_label, host_error=engine.host_error, counter_bits=engine._simulated.config.counter_bits)


@router.get("/links", response_model=list[LinkTraffic])
async def link_traffic(
    network: NetworkStore = Depends(get_store), monitoring: MonitoringStore = Depends(get_monitoring_store), settings: Settings = Depends(get_settings)
) -> list[LinkTraffic]:
    """Every link with its newest rates, utilization and state (up / busy / congested / down / unknown)."""
    thresholds = await _thresholds(monitoring, settings)
    by_id = {d.id: d for d in await network.list_devices()}
    return [aggregate.link_view(link, by_id, thresholds) for link in await network.list_links()]


@router.get("/summary", response_model=TrafficSummary)
async def traffic_summary(
    network: NetworkStore = Depends(get_store),
    traffic: TrafficStore = Depends(get_traffic_store),
    monitoring: MonitoringStore = Depends(get_monitoring_store),
    settings: Settings = Depends(get_settings),
) -> TrafficSummary:
    """Traffic by campus block, WAN and backbone links, busiest link, and this computer's REAL NIC."""
    thresholds = await _thresholds(monitoring, settings)
    links, devices = await network.list_links(), await network.list_devices()
    host = await traffic.list_samples("host", ["host"], limit=1)
    return aggregate.summarize(links, devices, thresholds, aggregate.host_view(host[-1] if host else None))


@router.get("/protocols", response_model=ProtocolDistribution)
async def protocol_distribution(
    minutes: float = Query(5.0, gt=0, le=1440),
    network: NetworkStore = Depends(get_store),
    traffic: TrafficStore = Depends(get_traffic_store),
) -> ProtocolDistribution:
    """SIMULATED protocol mix (TCP / UDP / DNS / ICMP / other) of the campus block uplinks."""
    links, devices = await network.list_links(), await network.list_devices()
    uplink_ids = [l.id for ls in aggregate.block_uplinks(links, devices).values() for l in ls]
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    samples = await traffic.list_samples("link", uplink_ids, since=since, limit=20000) if uplink_ids else []
    return aggregate.protocol_distribution(samples, minutes)


@router.get("/links/{link_id}/history", response_model=list[SeriesPoint])
async def link_history(
    link_id: str,
    hours: float = Query(1.0, gt=0, le=48),
    limit: int = Query(1000, ge=1, le=20000),
    bucket_s: int = Query(0, ge=0, le=3600, description="average samples into buckets of this many seconds (0 = raw)"),
    network: NetworkStore = Depends(get_store),
    traffic: TrafficStore = Depends(get_traffic_store),
) -> list[SeriesPoint]:
    if link_id not in {l.id for l in await network.list_links()}:
        raise NotFoundError(f"Link {link_id!r} not found")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return aggregate.series(await traffic.list_samples("link", [link_id], since=since, limit=limit), bucket_s)


@router.get("/blocks/history", response_model=list[BlockSeriesPoint])
async def blocks_history(
    hours: float = Query(1.0, gt=0, le=48),
    bucket_s: int = Query(60, ge=0, le=3600),
    network: NetworkStore = Depends(get_store),
    traffic: TrafficStore = Depends(get_traffic_store),
) -> list[BlockSeriesPoint]:
    """Traffic per campus block over time (the three block uplinks summed per cycle, then averaged per bucket)."""
    links, devices = await network.list_links(), await network.list_devices()
    mapping = {l.id: block for block, ls in aggregate.block_uplinks(links, devices).items() for l in ls}
    if not mapping:
        return []
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    samples = await traffic.list_samples("link", list(mapping), since=since, limit=20000)
    return aggregate.blocks_series(samples, mapping, bucket_s)


@router.get("/host/history", response_model=list[SeriesPoint])
async def host_history(
    hours: float = Query(1.0, gt=0, le=48),
    limit: int = Query(1000, ge=1, le=20000),
    bucket_s: int = Query(0, ge=0, le=3600),
    traffic: TrafficStore = Depends(get_traffic_store),
) -> list[SeriesPoint]:
    """REAL traffic of the computer running the monitor."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return aggregate.series(await traffic.list_samples("host", ["host"], since=since, limit=limit), bucket_s)
