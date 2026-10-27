"""The traffic engine: turns cumulative interface counters into rates, utilization and history.

Each cycle it reads every counter, subtracts the previous reading and divides by the elapsed
time (see counters.py). Campus links come from the SIMULATED counter source; the monitoring
host's own network interface comes from REAL psutil counters. Results are stored as
`traffic_samples` and the newest values are kept on each link document for fast dashboard reads.
"""
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import Settings
from app.monitoring.scheduler import PollingService
from app.network_model.models import LinkLatest
from app.network_model.store import NetworkStore
from app.simulator.traffic import PROTOCOLS, SimulatedTraffic
from app.traffic.counters import CounterReading, compute_rate
from app.traffic.host import HostNicSource
from app.traffic.models import TrafficSample
from app.traffic.store import TrafficStore

logger = logging.getLogger(__name__)


@dataclass
class TrafficReport:
    number: int
    samples: list[TrafficSample] = field(default_factory=list)
    discarded: int = 0  # readings dropped as suspected counter resets
    host_error: str | None = None
    duration_ms: float = 0.0


class TrafficEngine(PollingService):
    name = "traffic-engine"

    def __init__(
        self,
        network: NetworkStore,
        traffic: TrafficStore,
        simulated: SimulatedTraffic,
        host: HostNicSource | None,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        super().__init__()
        self._network = network
        self._traffic = traffic
        self._simulated = simulated
        self._host = host
        self._settings = settings
        self._clock = clock
        self._previous: dict[tuple[str, str], tuple[datetime, CounterReading]] = {}
        self.fallback_interval_s = settings.traffic_interval_s
        self.host_error: str | None = None
        self.host_label: str | None = None

    async def current_interval(self) -> float:
        return self._settings.traffic_interval_s

    def _rate_between(self, key: tuple[str, str], now: datetime, reading: CounterReading, capacity: float | None):
        """Rate since the previous reading of `key`, or None (first reading, reset, no time elapsed)."""
        previous = self._previous.get(key)
        self._previous[key] = (now, reading)
        if previous is None:
            return None, False
        before_time, before = previous
        rate = compute_rate(before, reading, (now - before_time).total_seconds(), capacity)
        return rate, rate is None  # (rate, discarded)

    async def run_cycle(self) -> TrafficReport:
        started = time.perf_counter()
        now = self._clock()
        links = await self._network.list_links()
        devices = await self._network.list_devices()
        report = TrafficReport(number=self.status.cycles_completed + 1)

        for stale in {k for k in self._previous if k[0] == "link"} - {("link", l.id) for l in links}:
            del self._previous[stale]

        updates: dict[str, LinkLatest] = {}
        if links and devices:
            readings = self._simulated.read(devices, links, now)
            for link in links:
                reading = readings[link.id]
                rate, discarded = self._rate_between(("link", link.id), now, reading, link.capacity_mbps)
                if discarded:
                    report.discarded += 1
                if rate is None:
                    continue
                total_bytes = rate.rx_bytes_delta + rate.tx_bytes_delta
                shares = self._simulated.shares.get(link.id, {})
                report.samples.append(
                    TrafficSample(
                        scope="link", ref_id=link.id, ts=now, source="simulated", dt_s=rate.dt_s, capacity_mbps=link.capacity_mbps,
                        rx_bytes=reading.rx_bytes, tx_bytes=reading.tx_bytes, rx_packets=reading.rx_packets, tx_packets=reading.tx_packets,
                        rx_mbps=rate.rx_mbps, tx_mbps=rate.tx_mbps, rx_pps=rate.rx_pps, tx_pps=rate.tx_pps, util_pct=rate.util_pct, wrapped=rate.wrapped,
                        proto_bytes={p: int(round(total_bytes * shares.get(p, 0.0))) for p in PROTOCOLS},
                    )
                )
                updates[link.id] = LinkLatest(ts=now, source="simulated", rx_mbps=rate.rx_mbps, tx_mbps=rate.tx_mbps,
                                              rx_pps=rate.rx_pps, tx_pps=rate.tx_pps, util_pct=rate.util_pct)

        self._read_host(now, report)

        await self._traffic.insert_samples(report.samples)
        for link_id, latest in updates.items():
            await self._network.update_link_fields(link_id, {"latest": latest.model_dump()})

        report.duration_ms = (time.perf_counter() - started) * 1000
        self.status.cycles_completed = report.number
        self.status.last_cycle_at = now
        self.status.last_cycle_duration_ms = round(report.duration_ms, 1)
        return report

    def _read_host(self, now: datetime, report: TrafficReport) -> None:
        """REAL counters of this computer. A failure here must never disturb the campus numbers."""
        if self._host is None:
            return
        try:
            reading = self._host.read()
        except Exception as exc:
            self.host_error = f"{type(exc).__name__}: {exc}"
            report.host_error = self.host_error
            logger.warning("Host NIC read failed: %s", self.host_error)
            return
        if reading is None:
            self.host_error = "no usable network interface found"
            report.host_error = self.host_error
            return
        self.host_error, self.host_label = None, reading.label
        rate, discarded = self._rate_between(("host", reading.label), now, reading.counters, reading.speed_mbps)
        if discarded:
            report.discarded += 1
        if rate is None:
            return
        c = reading.counters
        report.samples.append(
            TrafficSample(
                scope="host", ref_id="host", ts=now, source="real", label=reading.label, dt_s=rate.dt_s, capacity_mbps=reading.speed_mbps,
                rx_bytes=c.rx_bytes, tx_bytes=c.tx_bytes, rx_packets=c.rx_packets, tx_packets=c.tx_packets,
                rx_mbps=rate.rx_mbps, tx_mbps=rate.tx_mbps, rx_pps=rate.rx_pps, tx_pps=rate.tx_pps, util_pct=rate.util_pct, wrapped=rate.wrapped,
            )
        )
