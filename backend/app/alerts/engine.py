"""The alert engine: evaluates the rules against the current network state and keeps alerts in sync."""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.alerts import rules
from app.alerts.store import AlertStore
from app.config import Settings
from app.monitoring.engine import config_from_settings
from app.monitoring.scheduler import PollingService
from app.monitoring.store import MonitoringStore
from app.network_model.store import NetworkStore

logger = logging.getLogger(__name__)


@dataclass
class AlertReport:
    opened: int = 0
    updated: int = 0
    resolved: int = 0


class AlertEngine(PollingService):
    name = "alert-engine"

    def __init__(
        self,
        network: NetworkStore,
        alerts: AlertStore,
        monitoring: MonitoringStore,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        super().__init__()
        self._network, self._alerts, self._monitoring = network, alerts, monitoring
        self._settings, self._clock = settings, clock
        self.fallback_interval_s = settings.poll_interval_s

    async def _config(self):
        return await self._monitoring.get_config() or config_from_settings(self._settings)

    async def current_interval(self) -> float:
        return (await self._config()).poll_interval_s

    async def run_cycle(self) -> AlertReport:
        now = self._clock()
        config = await self._config()
        devices, links = await self._network.list_devices(), await self._network.list_links()
        open_alerts = await self._alerts.list_alerts(state="open", limit=1000)
        conditions = rules.active_conditions(
            devices, links, config.thresholds, config.alert_hysteresis_pct,
            {a.dedupe_key: a.severity for a in open_alerts}, self._settings.monitor_attached_to,
        )
        actions = rules.plan(open_alerts, conditions, now, config.alert_clear_cycles)

        await self._alerts.insert_alerts(actions.opened)
        for alert_id, fields in actions.updated:
            await self._alerts.update_alert(alert_id, fields)
        for alert_id in actions.resolved:
            await self._alerts.update_alert(alert_id, {"state": "resolved", "resolved_at": now, "updated_at": now})

        for alert in actions.opened:
            logger.info("ALERT opened: %s", alert.message)
        self.status.cycles_completed += 1
        self.status.last_cycle_at = now
        return AlertReport(len(actions.opened), len(actions.updated), len(actions.resolved))
