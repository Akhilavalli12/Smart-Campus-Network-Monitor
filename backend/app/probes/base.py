"""Common probe interface and result type.

The monitoring engine only knows about `Probe` and `ProbeResult`. It does not
care whether a result came from a real ICMP exchange or from the simulator.
"""
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol

from app.network_model.models import Device
from app.probes.stats import jitter_ms, packet_loss_pct


@dataclass(frozen=True)
class ProbeSettings:
    count: int = 5  # echo requests per probe
    timeout_s: float = 1.0  # how long to wait for each reply
    interval_s: float = 0.2  # gap between consecutive requests

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("count must be at least 1")
        if self.timeout_s <= 0 or self.interval_s < 0:
            raise ValueError("timeout_s must be positive and interval_s non-negative")


@dataclass(frozen=True)
class ProbeResult:
    device_id: str
    source: Literal["real", "simulated"]
    target: str  # address actually probed (a real IP) or "simulated"
    sent: int
    received: int
    rtts_ms: tuple[float, ...] = ()
    backend: str = ""  # "icmplib", "system-ping" or "simulator"
    error: str | None = None  # set when the PROBE could not run (not the same as packet loss)
    measured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def ok(self) -> bool:
        """True when the measurement is trustworthy (the probe itself ran)."""
        return self.error is None

    @property
    def loss_pct(self) -> float | None:
        return packet_loss_pct(self.sent, self.received) if self.ok and self.sent > 0 else None

    @property
    def rtt_min_ms(self) -> float | None:
        return min(self.rtts_ms) if self.rtts_ms else None

    @property
    def rtt_avg_ms(self) -> float | None:
        return sum(self.rtts_ms) / len(self.rtts_ms) if self.rtts_ms else None

    @property
    def rtt_max_ms(self) -> float | None:
        return max(self.rtts_ms) if self.rtts_ms else None

    @property
    def jitter_ms(self) -> float | None:
        return jitter_ms(self.rtts_ms)

    @property
    def reachable(self) -> bool:
        """At least one echo reply arrived."""
        return self.ok and self.received > 0


class Probe(Protocol):
    async def probe(
        self,
        device: Device,
        settings: ProbeSettings,
        *,
        upstream: Sequence[Device] = (),
    ) -> ProbeResult:
        """Measure `device`. `upstream` lists devices on the path from the monitoring station
        (used only by the simulator; a real network applies those effects by itself)."""
        ...


def probe_error(device: Device, source: str, target: str, backend: str, message: str) -> ProbeResult:
    """A result meaning 'the probe could not run', deliberately NOT 100% packet loss.

    Treating a broken monitoring tool (no permission, no ping binary) as a dead
    device would raise false alarms, so the engine must distinguish the two.
    """
    return ProbeResult(device_id=device.id, source=source, target=target, sent=0, received=0, backend=backend, error=message)
