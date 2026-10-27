"""Demo data: 24 hours of realistic history, produced by running the REAL engines in fast-forward.

Nothing here is invented by hand. The monitoring engine, traffic engine and alert engine run
against an in-memory copy of the campus while a clock jumps forward one minute per cycle; a
timeline of incidents injects faults at fixed moments. The resulting measurements, traffic
samples, status events and alerts are then written to MongoDB, so every chart and the alert history
are filled before the presentation starts.

HONESTY: all of this history is generated. Measurements carry backend="demo-backfill" and the
dashboard shows when demo history was loaded. Real measurements start when the live engines run.
"""
import logging
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.alerts.engine import AlertEngine
from app.config.settings import Settings
from app.demo.memory import InMemoryAlertStore, InMemoryMonitoringStore, InMemoryNetworkStore, InMemoryTrafficStore
from app.monitoring.engine import MonitoringEngine
from app.network_model.seed import seed_database
from app.probes.base import ProbeResult
from app.probes.dispatcher import ProbeDispatcher
from app.simulator import SimulatedProbe, SimulatorConfig
from app.simulator.faults import set_fault
from app.simulator.traffic import SimulatedTraffic, TrafficModelConfig
from app.traffic.engine import TrafficEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Incident:
    """A fault that starts `hours_ago` hours before the end of the history and lasts `minutes`."""

    hours_ago: float
    minutes: float
    device_id: str
    fault: str
    params: dict
    story: str


# Chosen so each alert type and both failure styles appear once, spread across the day.
INCIDENTS: tuple[Incident, ...] = (
    Incident(21.0, 25, "library-ap", "high_latency", {"rtt_ms": 220}, "Library access point slow (latency alert)"),
    Incident(16.5, 20, "cse-pc-2", "packet_loss", {"loss_pct": 35}, "CSE PC 2 losing packets (packet-loss alert)"),
    Incident(13.0, 30, "admin-switch", "congestion", {"utilization_pct": 96}, "Admin uplink congested (utilization alert)"),
    Incident(8.0, 12, "cse-switch", "offline", {}, "CSE switch down: root cause + 5 devices cut off (offline alert)"),
    Incident(4.5, 20, "cse-server", "high_latency", {"rtt_ms": 160}, "CSE lab server slow (latency alert)"),
    Incident(2.0, 8, "library-switch", "offline", {}, "Library switch down (offline alert)"),
)


class StepClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


class DemoRealProbe:
    """Stands in for the REAL Internet probe while generating history. Results are labelled SIMULATED / demo-backfill."""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(f"{seed}:demo-real")

    async def probe(self, device, settings, *, upstream=()):
        rtts = tuple(round(max(1.0, self._rng.gauss(14.0, 1.8)), 3) for _ in range(settings.count))
        return ProbeResult(device.id, "simulated", device.probe_target or "", settings.count, settings.count, rtts, "demo-backfill")


@dataclass
class DemoHistory:
    network: InMemoryNetworkStore
    monitoring: InMemoryMonitoringStore
    traffic: InMemoryTrafficStore
    alerts: InMemoryAlertStore
    start: datetime
    end: datetime
    cycles: int


async def generate_history(end: datetime | None = None, hours: float = 24.0, step_s: int = 60, seed: int = 42) -> DemoHistory:
    end = (end or datetime.now(timezone.utc)).replace(microsecond=0)
    start = end - timedelta(hours=hours)
    settings = Settings(_env_file=None, simulator_seed=seed)
    network, monitoring, traffic, alerts = InMemoryNetworkStore(), InMemoryMonitoringStore(), InMemoryTrafficStore(), InMemoryAlertStore()
    await seed_database(network)

    clock = StepClock(start)
    prober = ProbeDispatcher(real=DemoRealProbe(seed), simulated=SimulatedProbe(SimulatorConfig(seed=seed)))
    monitor = MonitoringEngine(network, monitoring, prober, settings, clock=clock)
    traffic_engine = TrafficEngine(
        network, traffic, SimulatedTraffic(TrafficModelConfig(seed=seed), vantage=settings.monitor_attached_to), None, settings, clock=clock
    )
    alert_engine = AlertEngine(network, alerts, monitoring, settings, clock=clock)

    # fault changes keyed by the cycle number at which they take effect
    changes: dict[int, list[tuple[str, str, dict]]] = {}
    total = int(hours * 3600 / step_s)
    for incident in INCIDENTS:
        begin = total - int(incident.hours_ago * 3600 / step_s)
        finish = begin + max(1, int(incident.minutes * 60 / step_s))
        if 0 < begin < total and finish < total:
            changes.setdefault(begin, []).append((incident.device_id, incident.fault, incident.params))
            changes.setdefault(finish, []).append((incident.device_id, "none", {}))

    for cycle in range(total + 1):
        clock.now = start + timedelta(seconds=cycle * step_s)
        for device_id, fault, params in changes.get(cycle, []):
            await set_fault(network, device_id, fault, params)
        await monitor.run_cycle()
        await traffic_engine.run_cycle()
        await alert_engine.run_cycle()
    return DemoHistory(network, monitoring, traffic, alerts, start, end, total + 1)


async def write_history(db, history: DemoHistory, *, retention_hours: int = 26) -> dict:
    """Replace the history collections in MongoDB with the generated data and sync the live device/link state."""
    from app.alerts.store import MongoAlertStore
    from app.monitoring.store import MongoMonitoringStore
    from app.network_model.store import MongoNetworkStore
    from app.traffic.store import MongoTrafficStore

    network, monitoring = MongoNetworkStore(db), MongoMonitoringStore(db, retention_hours)
    traffic, alerts = MongoTrafficStore(db, retention_hours), MongoAlertStore(db)
    for store in (network, monitoring, traffic, alerts):
        await store.ensure_indexes()
    for collection in ("measurements", "traffic_samples", "events", "alerts"):
        await db[collection].delete_many({})

    async def chunked(insert, rows, size=2000):
        for i in range(0, len(rows), size):
            await insert(rows[i : i + size])

    measurements = sorted((m for m in history.monitoring.measurements), key=lambda m: m.ts)
    samples = sorted(history.traffic.samples, key=lambda s: s.ts)
    events = sorted(history.monitoring.events, key=lambda e: e.ts)
    all_alerts = list(history.alerts.alerts.values())
    await chunked(monitoring.insert_measurements, measurements)
    await chunked(traffic.insert_samples, samples)
    await chunked(monitoring.insert_events, events)
    await chunked(alerts.insert_alerts, all_alerts)

    # the live engines resume from this state
    for device in history.network.devices.values():
        await network.update_device_fields(
            device.id,
            {
                "status": device.status,
                "last_seen": device.last_seen,
                "up_since": device.up_since,
                "consecutive_failures": device.consecutive_failures,
                "caused_by": device.caused_by,
                "monitoring_error": device.monitoring_error,
                "latest": device.latest.model_dump() if device.latest else None,
                "sim_state": {"fault": "none", "params": {}},
            },
        )
    for link in history.network.links.values():
        await network.update_link_fields(link.id, {"latest": link.latest.model_dump() if link.latest else None})

    info = {
        "loaded_at": history.end,
        "hours": (history.end - history.start).total_seconds() / 3600,
        "cycles": history.cycles,
        "measurements": len(measurements),
        "traffic_samples": len(samples),
        "events": len(events),
        "alerts": len(all_alerts),
    }
    await monitoring.save_demo_info(info)
    return info
