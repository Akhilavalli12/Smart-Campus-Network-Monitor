"""One call with everything the dashboard's KPI strip needs."""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.alerts.store import AlertStore
from app.api.dependencies import get_alert_store, get_monitoring_store, get_store, get_traffic_engine
from app.config import Settings, get_settings
from app.monitoring.engine import config_from_settings
from app.monitoring.store import MonitoringStore
from app.network_model.store import NetworkStore
from app.traffic.aggregate import util_state

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DeviceCounts(BaseModel):
    total: int
    online: int
    degraded: int
    offline: int
    unreachable: int
    unknown: int
    real: int
    simulated: int


class DashboardSummary(BaseModel):
    devices: DeviceCounts
    active_alerts: int
    critical_alerts: int
    warning_alerts: int
    avg_latency_ms: float | None
    avg_packet_loss_pct: float | None
    avg_utilization_pct: float | None
    utilization_state: str
    busiest_link_name: str | None
    busiest_link_util_pct: float | None
    demo_history_loaded_at: datetime | None


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    network: NetworkStore = Depends(get_store),
    alerts: AlertStore = Depends(get_alert_store),
    monitoring: MonitoringStore = Depends(get_monitoring_store),
    settings: Settings = Depends(get_settings),
) -> DashboardSummary:
    devices, links = await network.list_devices(), await network.list_links()
    thresholds = (await monitoring.get_config() or config_from_settings(settings)).thresholds
    count = lambda status: sum(1 for d in devices if d.status == status)

    reachable = [d for d in devices if d.status in ("online", "degraded") and d.latest and d.latest.window_rtt_avg_ms is not None]
    with_loss = [d for d in devices if d.latest and d.latest.window_loss_pct is not None]
    measured = [l for l in links if l.latest and l.latest.util_pct is not None]
    busiest = max(measured, key=lambda l: l.latest.util_pct, default=None)
    by_id = {d.id: d for d in devices}
    avg_util = sum(l.latest.util_pct for l in measured) / len(measured) if measured else None
    open_alerts = await alerts.list_alerts(state="open", limit=1000)
    demo = await monitoring.get_demo_info()

    return DashboardSummary(
        devices=DeviceCounts(total=len(devices), online=count("online"), degraded=count("degraded"), offline=count("offline"),
                             unreachable=count("unreachable"), unknown=count("unknown"),
                             real=sum(1 for d in devices if d.monitoring_mode == "real"), simulated=sum(1 for d in devices if d.monitoring_mode == "simulated")),
        active_alerts=len(open_alerts),
        critical_alerts=sum(1 for a in open_alerts if a.severity == "critical"),
        warning_alerts=sum(1 for a in open_alerts if a.severity == "warning"),
        avg_latency_ms=sum(d.latest.window_rtt_avg_ms for d in reachable) / len(reachable) if reachable else None,
        avg_packet_loss_pct=sum(d.latest.window_loss_pct for d in with_loss) / len(with_loss) if with_loss else None,
        avg_utilization_pct=avg_util,
        utilization_state=util_state(avg_util, thresholds),
        busiest_link_name=f"{by_id[busiest.a_id].name} to {by_id[busiest.b_id].name}" if busiest else None,
        busiest_link_util_pct=busiest.latest.util_pct if busiest else None,
        demo_history_loaded_at=demo.get("loaded_at") if demo else None,
    )
