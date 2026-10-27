"""SIMULATED campus traffic: cumulative interface counters, like those a real switch exposes.

Educational model, not a packet-level simulator. It captures:
  * leaf links (PC, access point, server) carry traffic with a daily rhythm plus slowly
    varying noise (an AR(1) process, so values drift instead of jumping randomly);
  * every other link carries the SUM of the links behind it (the switch uplink carries what
    its devices send), so the numbers add up from the leaves to the backbone;
  * the WAN link carries only a share of the backbone traffic (the rest stays on campus);
  * faults: an OFFLINE device (or one cut off behind an offline device) carries nothing; a
    CONGESTION fault drives the device's uplink to the requested utilization;
  * no link can carry more than its capacity.

Counters are 32-bit by default, like the classic SNMP ifInOctets counters, so they WRAP and the
traffic engine's wrap handling is exercised for real.
All numbers produced here are SIMULATED.
"""
import math
import random
from dataclasses import dataclass, field
from datetime import datetime

from app.network_model import topology
from app.network_model.enums import DeviceType, FaultType, LinkKind, MonitoringMode
from app.network_model.errors import InvalidNetworkData
from app.network_model.models import Device, Link
from app.simulator.model import DEFAULT_CONGESTION_UTILIZATION_PCT
from app.traffic.counters import CounterReading

PROTOCOLS = ("tcp", "udp", "dns", "icmp", "other")

# (download Mbps, upload Mbps) at the daily peak for one device, before the block's activity factor.
LEAF_PROFILES: dict[str, tuple[float, float]] = {
    DeviceType.PC.value: (5.0, 1.2),
    DeviceType.ACCESS_POINT.value: (14.0, 4.0),
    DeviceType.SERVER.value: (6.0, 16.0),
    DeviceType.SWITCH.value: (0.3, 0.3),
    DeviceType.CORE_SWITCH.value: (0.3, 0.3),
    DeviceType.EDGE_ROUTER.value: (0.3, 0.3),
}

# Typical share of bytes per protocol. DNS = port 53 (UDP or TCP); TCP/UDP exclude DNS.
BASE_SHARES: dict[str, dict[str, float]] = {
    DeviceType.PC.value: {"tcp": 0.72, "udp": 0.14, "dns": 0.05, "icmp": 0.01, "other": 0.08},
    DeviceType.ACCESS_POINT.value: {"tcp": 0.60, "udp": 0.28, "dns": 0.05, "icmp": 0.01, "other": 0.06},
    DeviceType.SERVER.value: {"tcp": 0.86, "udp": 0.05, "dns": 0.06, "icmp": 0.01, "other": 0.02},
}
DEFAULT_SHARES = {"tcp": 0.70, "udp": 0.15, "dns": 0.05, "icmp": 0.02, "other": 0.08}


@dataclass(frozen=True)
class TrafficModelConfig:
    seed: int = 42
    diurnal_amplitude: float = 0.5  # 0 = flat all day; 0.5 = night traffic is half of the daily peak
    peak_hour: float = 14.0  # local hour of the daily peak
    noise_sd: float = 0.10
    noise_persistence: float = 0.85  # AR(1) coefficient: how strongly noise carries over to the next sample
    wan_fraction: float = 0.7  # share of backbone traffic that goes to/from the Internet
    counter_bits: int = 32
    average_packet_bytes: float = 720.0
    block_activity: dict[str, float] = field(default_factory=lambda: {"cse": 1.0, "library": 0.75, "admin": 0.45})


@dataclass(frozen=True)
class LinkRate:
    down_mbps: float  # upstream device -> downstream device
    up_mbps: float  # downstream device -> upstream device
    shares: dict[str, float]


def diurnal_factor(now: datetime, config: TrafficModelConfig) -> float:
    """1.0 at the daily peak, (1 - amplitude) twelve hours away from it."""
    local = now.astimezone()
    hour = local.hour + local.minute / 60 + local.second / 3600
    wave = (1 + math.cos(2 * math.pi * (hour - config.peak_hour) / 24)) / 2  # 1 at the peak, 0 opposite
    return 1.0 - config.diurnal_amplitude * (1.0 - wave)


class SimulatedTraffic:
    """Generates cumulative counters for every link."""

    source = "simulated"

    def __init__(self, config: TrafficModelConfig | None = None, vantage: str = "core-switch") -> None:
        self.config = config or TrafficModelConfig()
        self._vantage = vantage
        self._rngs: dict[str, random.Random] = {}
        self._noise: dict[str, float] = {}
        self._totals: dict[str, list[float]] = {}  # link -> [rx_bytes, tx_bytes, rx_packets, tx_packets]
        self._offsets: dict[str, list[int]] = {}
        self._packet_size: dict[str, float] = {}
        self._last_t: datetime | None = None
        self.shares: dict[str, dict[str, float]] = {}  # protocol shares of the latest read
        self.rates: dict[str, LinkRate] = {}  # rates of the latest read

    # -------------------------------------------------------------- randomness
    def _rng(self, link_id: str) -> random.Random:
        if link_id not in self._rngs:
            self._rngs[link_id] = random.Random(f"{self.config.seed}:traffic:{link_id}")
            self._noise[link_id] = 0.0
        return self._rngs[link_id]

    def _advance_noise(self, link_id: str) -> tuple[float, dict[str, float]]:
        """One AR(1) step plus protocol-share jitter. Every link draws the same numbers every read,
        so injecting a fault never shifts later values."""
        rng = self._rng(link_id)
        c = self.config
        self._noise[link_id] = c.noise_persistence * self._noise[link_id] + rng.gauss(0.0, c.noise_sd)
        jitter = {p: rng.gauss(0.0, 0.05) for p in PROTOCOLS}
        return self._noise[link_id], jitter

    # -------------------------------------------------------------- rates
    def compute_rates(self, devices: list[Device], links: list[Link], now: datetime) -> dict[str, LinkRate]:
        c = self.config
        by_id = {d.id: d for d in devices}
        factor = diurnal_factor(now, c)
        noise: dict[str, float] = {}
        jitter: dict[str, dict[str, float]] = {}
        for link in sorted(links, key=lambda l: l.id):
            noise[link.id], jitter[link.id] = self._advance_noise(link.id)

        down = {d.id for d in devices if d.monitoring_mode == MonitoringMode.SIMULATED and d.sim_state.fault == FaultType.OFFLINE}

        def cut_off(device_id: str) -> bool:
            if device_id in down:
                return True
            try:
                return any(p in down for p in topology.reachability_path(by_id, self._vantage, device_id))
            except InvalidNetworkData:
                return False

        child_links: dict[str, list[Link]] = {}
        for link in links:
            child_links.setdefault(link.a_id, []).append(link)

        def depth(link: Link) -> int:
            try:
                return topology.depth_of(by_id, link.b_id)
            except InvalidNetworkData:
                return 0

        rates: dict[str, LinkRate] = {}
        for link in sorted(links, key=depth, reverse=True):  # deepest first: leaves before the links that sum them
            child, parent = by_id[link.b_id], by_id[link.a_id]
            kids = child_links.get(child.id, [])
            shares = self._leaf_shares(child, jitter[link.id])
            if cut_off(child.id) or parent.id in down:
                rates[link.id] = LinkRate(0.0, 0.0, shares)
                continue
            if kids:
                kid_rates = [rates[k.id] for k in kids if k.id in rates]
                d_sum, u_sum = sum(r.down_mbps for r in kid_rates), sum(r.up_mbps for r in kid_rates)
                weight = d_sum + u_sum
                if weight > 0:
                    shares = {p: sum((r.down_mbps + r.up_mbps) * r.shares[p] for r in kid_rates) / weight for p in PROTOCOLS}
            else:
                base_down, base_up = LEAF_PROFILES.get(child.type, (0.5, 0.5))
                activity = c.block_activity.get(child.block, 1.0)
                scale = activity * factor * max(0.2, 1.0 + noise[link.id])
                d_sum, u_sum = base_down * scale, base_up * scale
            if link.kind == LinkKind.WAN.value:
                d_sum, u_sum = d_sum * c.wan_fraction, u_sum * c.wan_fraction
            if child.monitoring_mode == MonitoringMode.SIMULATED and child.sim_state.fault == FaultType.CONGESTION:
                utilization = child.sim_state.params.get("utilization_pct", DEFAULT_CONGESTION_UTILIZATION_PCT)
                utilization = max(0.0, min(100.0, utilization))
                d_sum = link.capacity_mbps * utilization / 100.0 * (1.0 + 0.02 * noise[link.id])
                u_sum = 0.4 * d_sum
            rates[link.id] = LinkRate(min(d_sum, link.capacity_mbps), min(u_sum, link.capacity_mbps), shares)
        return rates

    def _leaf_shares(self, device: Device, jitter: dict[str, float]) -> dict[str, float]:
        base = BASE_SHARES.get(device.type, DEFAULT_SHARES)
        raw = {p: max(0.001, base[p] * (1.0 + jitter[p])) for p in PROTOCOLS}
        total = sum(raw.values())
        return {p: v / total for p, v in raw.items()}

    # -------------------------------------------------------------- counters
    def read(self, devices: list[Device], links: list[Link], now: datetime) -> dict[str, CounterReading]:
        """Advance every link's counters to `now` and return them."""
        c = self.config
        modulus = 1 << c.counter_bits
        rates = self.compute_rates(devices, links, now)
        dt = 0.0 if self._last_t is None else max(0.0, (now - self._last_t).total_seconds())
        self._last_t = now
        self.rates = rates
        self.shares = {link_id: rate.shares for link_id, rate in rates.items()}

        readings: dict[str, CounterReading] = {}
        for link in links:
            if link.id not in self._totals:
                seed_rng = random.Random(f"{c.seed}:offset:{link.id}")
                self._totals[link.id] = [0.0, 0.0, 0.0, 0.0]
                self._offsets[link.id] = [seed_rng.randrange(modulus) for _ in range(4)]  # counters do not start at 0
                self._packet_size[link.id] = c.average_packet_bytes * seed_rng.uniform(0.8, 1.2)
            rate = rates[link.id]
            totals = self._totals[link.id]
            rx_bytes = rate.down_mbps * 1e6 / 8 * dt
            tx_bytes = rate.up_mbps * 1e6 / 8 * dt
            totals[0] += rx_bytes
            totals[1] += tx_bytes
            totals[2] += rx_bytes / self._packet_size[link.id]
            totals[3] += tx_bytes / self._packet_size[link.id]
            off = self._offsets[link.id]
            readings[link.id] = CounterReading(
                rx_bytes=(off[0] + int(totals[0])) % modulus,
                tx_bytes=(off[1] + int(totals[1])) % modulus,
                rx_packets=(off[2] + int(totals[2])) % modulus,
                tx_packets=(off[3] + int(totals[3])) % modulus,
                bits=c.counter_bits,
            )
        return readings
