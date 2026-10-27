"""SimulatedProbe: produces ICMP-like results from the educational model.

Deterministic: every device owns its own seeded random stream, so a run with the
same seed and the same sequence of probes gives identical numbers, and probing
one device never disturbs another device's stream.
"""
import random
from collections.abc import Sequence

from app.network_model.enums import MonitoringMode
from app.network_model.models import Device
from app.probes.base import ProbeResult, ProbeSettings, probe_error
from app.simulator.model import DEFAULT_BASE_RTT_MS, SimulatorConfig, combine_path, effect_of


class SimulatedProbe:
    def __init__(self, config: SimulatorConfig | None = None) -> None:
        self._config = config or SimulatorConfig()
        self._streams: dict[str, random.Random] = {}

    def _stream(self, device_id: str) -> random.Random:
        if device_id not in self._streams:
            # A str seed is hashed with SHA-512 by `random`, so this is stable across runs and machines.
            self._streams[device_id] = random.Random(f"{self._config.seed}:{device_id}")
        return self._streams[device_id]

    async def probe(self, device: Device, settings: ProbeSettings, *, upstream: Sequence[Device] = ()) -> ProbeResult:
        if device.monitoring_mode != MonitoringMode.SIMULATED:
            return probe_error(device, "simulated", "simulated", "simulator", "SimulatedProbe cannot measure a real-mode device")

        config = self._config
        rng = self._stream(device.id)
        path = combine_path(
            [effect_of(d, config) for d in (*upstream, device)],
            baseline_loss=config.baseline_loss_probability,
        )
        base = device.base_rtt_ms or DEFAULT_BASE_RTT_MS
        mean_rtt = base + path.extra_latency_ms

        rtts: list[float] = []
        for _ in range(settings.count):
            # Always draw the same four numbers per echo, so toggling a fault never shifts later samples.
            loss_draw = rng.random()
            noise = rng.gauss(0.0, config.jitter_ratio)
            spike_draw = rng.random()
            spike_scale = rng.uniform(*config.spike_multiplier)

            if path.offline or loss_draw < path.loss_probability:
                continue
            sample = mean_rtt * max(0.5, 1.0 + noise)
            if spike_draw < config.spike_probability:
                sample += base * spike_scale
            rtts.append(round(sample, 3))

        return ProbeResult(
            device_id=device.id,
            source="simulated",
            target="simulated",
            sent=settings.count,
            received=len(rtts),
            rtts_ms=tuple(rtts),
            backend="simulator",
        )
