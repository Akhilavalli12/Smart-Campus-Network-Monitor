"""The monitoring engine: a polling loop that probes every device and maintains its status.

One cycle:
  1. read the runtime configuration and the device list (so edits apply on the next cycle)
  2. work out, for each device, which devices a probe must pass through (from the monitoring station)
  3. probe all devices concurrently (a failing probe is isolated and never aborts the cycle)
  4. evaluate devices nearest the station first, so a root cause is known before its dependants
  5. persist measurements, device state and status-change events

The API never probes. It only reads what this engine stored.
"""
import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import Settings
from app.monitoring.models import Measurement, MonitoringConfig, StatusEvent
from app.monitoring.scheduler import EngineStatus, PollingService  # noqa: F401  (EngineStatus re-exported)
from app.monitoring.state_machine import HealthState, Rules, Transition, step, window_counts, window_stats
from app.monitoring.store import MonitoringStore
from app.network_model import topology
from app.network_model.enums import DeviceStatus
from app.network_model.errors import InvalidNetworkData
from app.network_model.models import Device, LatestMetrics
from app.network_model.store import NetworkStore
from app.probes.base import Probe, ProbeResult, ProbeSettings, probe_error
from app.probes.dispatcher import probe_settings_from

logger = logging.getLogger(__name__)

MAX_CONCURRENT_PROBES = 20


def config_from_settings(settings: Settings) -> MonitoringConfig:
    """Defaults used until someone saves a configuration through the API."""
    return MonitoringConfig(
        poll_interval_s=settings.poll_interval_s,
        failure_confirmations=settings.failure_confirmations,
        recovery_confirmations=settings.recovery_confirmations,
        window_cycles=settings.window_cycles,
    )


@dataclass
class CycleReport:
    number: int
    started_at: datetime
    duration_ms: float
    probed: int
    probe_errors: int
    events: list[StatusEvent] = field(default_factory=list)
    skipped_reason: str | None = None


class MonitoringEngine(PollingService):
    def __init__(
        self,
        network: NetworkStore,
        monitoring: MonitoringStore,
        prober: Probe,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._network = network
        self._monitoring = monitoring
        self._prober = prober
        self._settings = settings
        self._clock = clock
        self._states: dict[str, HealthState] = {}
        super().__init__()
        self.fallback_interval_s = settings.poll_interval_s

    # ------------------------------------------------------------------ one cycle
    name = "monitoring-engine"

    async def _load_config(self) -> MonitoringConfig:
        return await self._monitoring.get_config() or config_from_settings(self._settings)

    async def current_interval(self) -> float:
        return (await self._load_config()).poll_interval_s

    async def run_cycle(self) -> CycleReport:
        started_wall = time.perf_counter()
        config = await self._load_config()
        devices = await self._network.list_devices()
        number = self.status.cycles_completed + 1
        now = self._clock()

        if not devices:
            return self._finish(CycleReport(number, now, 0.0, 0, 0, skipped_reason="no devices registered"), started_wall)

        by_id = {d.id: d for d in devices}
        try:
            paths = {d.id: topology.reachability_path(by_id, self._settings.monitor_attached_to, d.id) for d in devices}
        except InvalidNetworkData as exc:
            # A misconfigured vantage point would make every dependency decision wrong: refuse to guess.
            self.status.last_error = str(exc)
            logger.error("Monitoring cycle skipped: %s", exc)
            return self._finish(CycleReport(number, now, 0.0, 0, 0, skipped_reason=str(exc)), started_wall)

        for device in devices:
            self._states.setdefault(device.id, HealthState.from_device(device))
        for stale in set(self._states) - set(by_id):
            del self._states[stale]

        probe_settings = probe_settings_from(self._settings)
        results = await self._probe_all(devices, by_id, paths, probe_settings)

        rules = Rules(
            failure_confirmations=config.failure_confirmations,
            recovery_confirmations=config.recovery_confirmations,
            window_cycles=config.window_cycles,
            latency_warn_ms=config.thresholds.latency_warn_ms,
            loss_warn_pct=config.thresholds.loss_warn_pct,
        )

        # Nearest to the monitoring station first: an upstream device's new status is known before its dependants.
        order = sorted(devices, key=lambda d: len(paths[d.id]))
        measurements: list[Measurement] = []
        events: list[StatusEvent] = []
        updates: dict[str, dict] = {}

        for device in order:
            result = results[device.id]
            state = self._states[device.id]
            upstream_offline = self._first_offline(paths[device.id], by_id)
            transition = step(state, result, rules, upstream_offline, now)

            measurements.append(self._measurement(device, result, state, now))
            updates[device.id] = self._device_fields(result, state, now)
            if transition is not None:
                events.append(self._event(device, transition, now))

        await self._monitoring.insert_measurements(measurements)
        for device_id, fields in updates.items():
            await self._network.update_device_fields(device_id, fields)
        await self._monitoring.insert_events(events)

        report = CycleReport(
            number=number,
            started_at=now,
            duration_ms=0.0,
            probed=len(devices),
            probe_errors=sum(1 for r in results.values() if not r.ok),
            events=events,
        )
        return self._finish(report, started_wall)

    # ------------------------------------------------------------------ helpers
    def _finish(self, report: CycleReport, started_wall: float) -> CycleReport:
        report.duration_ms = (time.perf_counter() - started_wall) * 1000
        self.status.cycles_completed = report.number
        self.status.last_cycle_at = report.started_at
        self.status.last_cycle_duration_ms = round(report.duration_ms, 1)
        return report

    def _first_offline(self, path: list[str], by_id: dict[str, Device]) -> tuple[str, str] | None:
        for device_id in path:  # path runs from the monitoring station outwards
            if self._states[device_id].status == DeviceStatus.OFFLINE.value:
                return device_id, by_id[device_id].name
        return None

    async def _probe_all(
        self, devices: list[Device], by_id: dict[str, Device], paths: dict[str, list[str]], settings: ProbeSettings
    ) -> dict[str, ProbeResult]:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)
        deadline = settings.count * (settings.timeout_s + settings.interval_s) + 5.0

        async def one(device: Device) -> tuple[str, ProbeResult]:
            upstream = [by_id[i] for i in paths[device.id]]
            async with semaphore:
                try:
                    result = await asyncio.wait_for(self._prober.probe(device, settings, upstream=upstream), timeout=deadline)
                except asyncio.TimeoutError:
                    result = probe_error(device, device.monitoring_mode, device.probe_target or "", "engine", "probe exceeded the engine deadline")
                except Exception as exc:  # exception isolation: one broken probe never aborts the cycle
                    logger.exception("Probe of %s raised", device.id)
                    result = probe_error(device, device.monitoring_mode, device.probe_target or "", "engine", f"{type(exc).__name__}: {exc}")
            return device.id, result

        return dict(await asyncio.gather(*(one(d) for d in devices)))

    @staticmethod
    def _measurement(device: Device, result: ProbeResult, state: HealthState, now: datetime) -> Measurement:
        return Measurement(
            device_id=device.id,
            ts=now,
            source=result.source,
            backend=result.backend,
            target=result.target,
            sent=result.sent,
            received=result.received,
            loss_pct=result.loss_pct,
            rtt_min_ms=result.rtt_min_ms,
            rtt_avg_ms=result.rtt_avg_ms,
            rtt_max_ms=result.rtt_max_ms,
            jitter_ms=result.jitter_ms,
            error=result.error,
            status=state.status,
        )

    @staticmethod
    def _device_fields(result: ProbeResult, state: HealthState, now: datetime) -> dict:
        fields: dict = {
            "status": state.status,
            "last_seen": state.last_seen,
            "up_since": state.up_since,
            "consecutive_failures": state.consecutive_failures,
            "caused_by": state.caused_by,
            "monitoring_error": result.error,
        }
        if result.ok:
            window_loss, window_avg = window_stats(state.window)
            window_sent, window_received = window_counts(state.window)
            fields["latest"] = LatestMetrics(
                at=now,
                source=result.source,
                backend=result.backend,
                target=result.target,
                sent=result.sent,
                received=result.received,
                loss_pct=result.loss_pct,
                rtt_min_ms=result.rtt_min_ms,
                rtt_avg_ms=result.rtt_avg_ms,
                rtt_max_ms=result.rtt_max_ms,
                jitter_ms=result.jitter_ms,
                window_loss_pct=window_loss,
                window_rtt_avg_ms=window_avg,
                window_sent=window_sent,
                window_received=window_received,
            ).model_dump()
        return fields

    @staticmethod
    def _event(device: Device, transition: Transition, now: datetime) -> StatusEvent:
        return StatusEvent(
            ts=now,
            device_id=device.id,
            device_name=device.name,
            from_status=transition.from_status,
            to_status=transition.to_status,
            reason=transition.reason,
            caused_by=transition.caused_by,
        )
