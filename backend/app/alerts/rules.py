"""Alert rules: pure functions that compare the current network state with the open alerts.

Rules
-----
DEVICE_OFFLINE     critical when a device's status is OFFLINE (already debounced by the state machine).
                   Devices that are UNREACHABLE because of it get NO alert of their own; they are listed on the
                   root-cause alert (one meaningful alert instead of one per child).
HIGH_LATENCY       windowed average RTT >= warning (warning) or >= critical (critical).
HIGH_PACKET_LOSS   windowed packet loss >= warning / critical.
HIGH_UTILIZATION   link utilization >= warning / critical.

Thresholds are configurable system settings, not networking standards.
Hysteresis: an OPEN alert is kept until the value falls below threshold x (1 - hysteresis %), so a value
hovering around a threshold does not open and close alerts repeatedly.
Suppression: a latency/loss condition on a device is hidden when a device on the path to it has the same
condition (a slow switch makes everything behind it slow; the switch is the root cause).
"""
from dataclasses import dataclass, field
from datetime import datetime

from app.alerts.models import Alert, AlertType, Severity
from app.monitoring.models import Thresholds
from app.network_model import topology
from app.network_model.errors import InvalidNetworkData
from app.network_model.models import Device, Link
from app.monitoring.state_machine import MIN_LOST_ECHOES
from app.traffic.aggregate import CAMPUS_BLOCKS, DOWN_STATUSES

UP_STATUSES = ("online", "degraded")


@dataclass(frozen=True)
class Condition:
    key: str
    type: str
    severity: str
    device_id: str | None
    device_name: str | None
    link_id: str | None
    title: str
    message: str
    metrics: dict
    last_response_at: datetime | None = None
    affected: tuple[str, ...] = ()


@dataclass
class Actions:
    opened: list[Alert] = field(default_factory=list)
    updated: list[tuple[str, dict]] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)


def grade(value: float | None, warn: float, crit: float, open_severity: str | None, hysteresis_pct: float) -> str | None:
    """Severity for a value, with hysteresis for an alert that is already open."""
    if value is None:
        return None
    keep = 1.0 - hysteresis_pct / 100.0
    if value >= crit or (open_severity == Severity.CRITICAL.value and value >= crit * keep):
        return Severity.CRITICAL.value
    if value >= warn or (open_severity is not None and value >= warn * keep):
        return Severity.WARNING.value
    return None


def _clock(ts: datetime | None) -> str:
    return ts.astimezone().strftime("%H:%M:%S") if ts else "never"


def active_conditions(
    devices: list[Device],
    links: list[Link],
    thresholds: Thresholds,
    hysteresis_pct: float,
    open_severity: dict[str, str],
    vantage: str,
) -> dict[str, Condition]:
    by_id = {d.id: d for d in devices}
    try:
        paths = {d.id: topology.reachability_path(by_id, vantage, d.id) for d in devices}
    except InvalidNetworkData:
        paths = {d.id: [] for d in devices}
    result: dict[str, Condition] = {}

    # --- device offline (root cause) ---
    for device in devices:
        if device.status != "offline":
            continue
        affected = tuple(sorted(d.id for d in devices if d.caused_by == device.id))
        loss = 100.0  # OFFLINE means no echo reply for several consecutive cycles
        extra = f" {len(affected)} downstream device(s) are cut off by this failure." if affected else ""
        key = f"{AlertType.DEVICE_OFFLINE.value}:{device.id}"
        result[key] = Condition(
            key=key, type=AlertType.DEVICE_OFFLINE.value, severity=Severity.CRITICAL.value, device_id=device.id, device_name=device.name, link_id=None,
            title=f"{device.name} is offline",
            message=f"{device.name} is unreachable. Packet loss: {loss:.0f}%. Last response: {_clock(device.last_seen)}.{extra}",
            metrics={"packet_loss_pct": round(loss, 1), "consecutive_failures": device.consecutive_failures, "ip": device.ip},
            last_response_at=device.last_seen, affected=affected,
        )

    # --- latency / loss (reachable devices only) ---
    raw: dict[tuple[str, str], Condition] = {}
    for device in devices:
        if device.status not in UP_STATUSES or device.latest is None:
            continue
        if device.consecutive_failures > 0:
            continue  # the device just stopped answering: this is the start of an outage, not "high loss"
        latest = device.latest
        for kind, value, warn, crit, unit in (
            (AlertType.HIGH_LATENCY.value, latest.window_rtt_avg_ms, thresholds.latency_warn_ms, thresholds.latency_crit_ms, "ms"),
            (AlertType.HIGH_PACKET_LOSS.value, latest.window_loss_pct, thresholds.loss_warn_pct, thresholds.loss_crit_pct, "%"),
        ):
            key = f"{kind}:{device.id}"
            severity = grade(value, warn, crit, open_severity.get(key), hysteresis_pct)
            if severity is None:
                continue
            if kind == AlertType.HIGH_PACKET_LOSS.value and latest.window_sent is not None and latest.window_sent - (latest.window_received or 0) < MIN_LOST_ECHOES:
                continue  # one or two lost echoes are noise, not a loss problem
            what = "latency" if kind == AlertType.HIGH_LATENCY.value else "packet loss"
            shown = f"{value:.0f} ms" if unit == "ms" else f"{value:.1f}%"
            limit = crit if severity == Severity.CRITICAL.value else warn
            raw[(kind, device.id)] = Condition(
                key=key, type=kind, severity=severity, device_id=device.id, device_name=device.name, link_id=None,
                title=f"High {what} on {device.name}",
                message=f"{device.name} {what} is {shown} (configured {severity} threshold {limit:g}{' ms' if unit == 'ms' else '%'}). Last response: {_clock(device.last_seen)}.",
                metrics={("avg_latency_ms" if unit == "ms" else "packet_loss_pct"): round(value, 2), "threshold": limit, "ip": device.ip},
                last_response_at=device.last_seen,
            )
    for (kind, device_id), condition in raw.items():
        # a device behind a slow/lossy/degraded device is slow because of it: the upstream device is the root cause
        shadowed = any((kind, up) in raw or by_id[up].status == "degraded" for up in paths.get(device_id, []))
        if not shadowed:
            result[condition.key] = condition

    # --- link utilization ---
    for link in links:
        latest = link.latest
        a, b = by_id.get(link.a_id), by_id.get(link.b_id)
        if latest is None or latest.util_pct is None or a is None or b is None:
            continue
        if a.status in DOWN_STATUSES or b.status in DOWN_STATUSES:
            continue
        key = f"{AlertType.HIGH_UTILIZATION.value}:{link.id}"
        severity = grade(latest.util_pct, thresholds.util_warn_pct, thresholds.util_crit_pct, open_severity.get(key), hysteresis_pct)
        if severity is None:
            continue
        limit = thresholds.util_crit_pct if severity == Severity.CRITICAL.value else thresholds.util_warn_pct
        block = CAMPUS_BLOCKS.get(b.block)
        scope = f"{block} network" if block and a.type == "core_switch" else f"{a.name} to {b.name} link"
        result[key] = Condition(
            key=key, type=AlertType.HIGH_UTILIZATION.value, severity=severity, device_id=b.id, device_name=b.name, link_id=link.id,
            title=f"High bandwidth utilization on {scope}",
            message=(f"{scope[0].upper() + scope[1:]} bandwidth utilization exceeded the configured {severity} threshold ({limit:g}%). "
                     f"Current utilization: {latest.util_pct:.0f}% (download {latest.rx_mbps:.1f} Mbps, upload {latest.tx_mbps:.1f} Mbps of {link.capacity_mbps:g} Mbps)."),
            metrics={"utilization_pct": round(latest.util_pct, 1), "rx_mbps": round(latest.rx_mbps, 2), "tx_mbps": round(latest.tx_mbps, 2),
                     "capacity_mbps": link.capacity_mbps, "threshold": limit},
        )
    return result


PRIMARY_METRIC = {
    AlertType.HIGH_LATENCY.value: "avg_latency_ms",
    AlertType.HIGH_PACKET_LOSS.value: "packet_loss_pct",
    AlertType.HIGH_UTILIZATION.value: "utilization_pct",
    AlertType.DEVICE_OFFLINE.value: "packet_loss_pct",
}


def with_peak(metrics: dict, previous: dict | None, alert_type: str) -> dict:
    """Keep the highest value the alert has reached, so a resolved alert still shows how bad it got."""
    key = PRIMARY_METRIC[alert_type]
    value = metrics.get(key)
    peak = value if isinstance(value, (int, float)) else None
    old = (previous or {}).get("peak")
    if isinstance(old, (int, float)) and (peak is None or old > peak):
        peak = old
    return {**metrics, "peak": peak}


def plan(open_alerts: list[Alert], conditions: dict[str, Condition], now: datetime, clear_cycles: int = 3) -> Actions:
    """Turn (open alerts, current conditions) into the changes to store.

    Clear delay: a latency / loss / utilization alert resolves only after its condition has been absent for
    `clear_cycles` consecutive checks, so a value flickering around a threshold stays ONE alert.
    An offline alert resolves at once (the state machine already waited for recovery confirmations).
    """
    actions = Actions()
    open_by_key = {a.dedupe_key: a for a in open_alerts}  # one open alert per key (de-duplication)
    for key, cond in conditions.items():
        existing = open_by_key.get(key)
        if existing is None:
            actions.opened.append(
                Alert(type=cond.type, severity=cond.severity, dedupe_key=key, device_id=cond.device_id, device_name=cond.device_name, link_id=cond.link_id,
                      title=cond.title, message=cond.message, metrics=with_peak(cond.metrics, None, cond.type), affected_device_ids=list(cond.affected),
                      last_response_at=cond.last_response_at, opened_at=now, updated_at=now)
            )
            continue
        fields = {"severity": cond.severity, "title": cond.title, "message": cond.message, "metrics": with_peak(cond.metrics, existing.metrics, cond.type),
                  "affected_device_ids": list(cond.affected), "last_response_at": cond.last_response_at, "updated_at": now, "quiet_cycles": 0}
        actions.updated.append((existing.id, fields))
    for key, alert in open_by_key.items():
        if key in conditions:
            continue
        quiet = alert.quiet_cycles + 1
        if alert.type == AlertType.DEVICE_OFFLINE.value or quiet >= clear_cycles:
            actions.resolved.append(alert.id)
        else:
            actions.updated.append((alert.id, {"quiet_cycles": quiet, "updated_at": now}))
    return actions
