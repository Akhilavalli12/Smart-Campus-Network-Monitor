"""Routes each device to the right probe based on its monitoring mode."""
from collections.abc import Sequence

from app.config import Settings
from app.network_model.enums import MonitoringMode
from app.network_model.models import Device
from app.probes.base import Probe, ProbeResult, ProbeSettings
from app.probes.icmp import RealIcmpProbe
from app.simulator import SimulatedProbe, SimulatorConfig


class ProbeDispatcher:
    """The only probe object the monitoring engine needs: it hides real vs simulated."""

    def __init__(self, real: Probe, simulated: Probe) -> None:
        self._real = real
        self._simulated = simulated

    async def probe(self, device: Device, settings: ProbeSettings, *, upstream: Sequence[Device] = ()) -> ProbeResult:
        chosen = self._real if device.monitoring_mode == MonitoringMode.REAL else self._simulated
        return await chosen.probe(device, settings, upstream=upstream)


def probe_settings_from(settings: Settings) -> ProbeSettings:
    return ProbeSettings(count=settings.probe_count, timeout_s=settings.probe_timeout_s, interval_s=settings.probe_interval_s)


def build_probe_dispatcher(settings: Settings) -> ProbeDispatcher:
    return ProbeDispatcher(
        real=RealIcmpProbe(settings.icmp_backend),
        simulated=SimulatedProbe(SimulatorConfig(seed=settings.simulator_seed)),
    )
