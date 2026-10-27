"""Device status state machine. Pure logic: no I/O, no clocks, fully unit-testable.

States: UNKNOWN (never measured) -> ONLINE <-> DEGRADED -> OFFLINE / UNREACHABLE.

Rules
-----
* A cycle is a REPLY cycle if at least one echo reply arrived, otherwise a FAILED cycle.
* OFFLINE needs `failure_confirmations` consecutive FAILED cycles (never one lost ping).
* If that happens while a device on the path to it is OFFLINE, the device is UNREACHABLE
  (upstream failure, caused_by = the nearest-to-the-monitor offline device) instead of OFFLINE.
* Leaving OFFLINE/UNREACHABLE needs `recovery_confirmations` consecutive REPLY cycles.
* DEGRADED is judged on a rolling window of the last `window_cycles` cycles, so a single
  lost echo does not flip a healthy device: windowed loss (and at least MIN_LOST_ECHOES really lost) or average RTT above the warning threshold.
  It is only judged once the window holds MIN_CYCLES_FOR_DEGRADED cycles.
* A probe that could not RUN (result.error set) changes nothing: a broken monitor is not a dead device.
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from app.network_model.enums import DeviceStatus
from app.network_model.models import Device
from app.probes.base import ProbeResult

S = DeviceStatus
MIN_CYCLES_FOR_DEGRADED = 3
# Packet loss only counts as a problem when at least this many echoes were really lost in the window.
# Even a healthy path drops an occasional echo (0.2 % in our model); two such drops out of 25 look like 8 %.
MIN_LOST_ECHOES = 3
DOWN_STATES = (S.OFFLINE.value, S.UNREACHABLE.value)
UP_STATES = (S.ONLINE.value, S.DEGRADED.value)


@dataclass(frozen=True)
class CycleSample:
    sent: int
    received: int
    rtt_sum_ms: float
    rtt_count: int


@dataclass(frozen=True)
class Rules:
    failure_confirmations: int
    recovery_confirmations: int
    window_cycles: int
    latency_warn_ms: float
    loss_warn_pct: float


@dataclass(frozen=True)
class Transition:
    from_status: str
    to_status: str
    reason: str
    caused_by: str | None = None


@dataclass
class HealthState:
    status: str = S.UNKNOWN.value
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    window: deque = field(default_factory=deque)  # deque[CycleSample]
    caused_by: str | None = None
    up_since: datetime | None = None
    last_seen: datetime | None = None

    @classmethod
    def from_device(cls, device: Device) -> "HealthState":
        """Resume from what was persisted (the rolling window starts empty after a restart)."""
        return cls(
            status=device.status,
            consecutive_failures=device.consecutive_failures,
            caused_by=device.caused_by,
            up_since=device.up_since,
            last_seen=device.last_seen,
        )


def window_counts(window) -> tuple[int, int]:
    """(echoes sent, echoes received) over the window."""
    return sum(c.sent for c in window), sum(c.received for c in window)


def window_stats(window) -> tuple[float | None, float | None]:
    """(loss %, average RTT ms) over the window; None where there is nothing to average."""
    sent = sum(c.sent for c in window)
    received = sum(c.received for c in window)
    rtt_count = sum(c.rtt_count for c in window)
    loss = (sent - received) / sent * 100.0 if sent else None
    avg = sum(c.rtt_sum_ms for c in window) / rtt_count if rtt_count else None
    return loss, avg


def _degraded_reason(state: HealthState, rules: Rules) -> str | None:
    if len(state.window) < MIN_CYCLES_FOR_DEGRADED:
        return None
    loss, avg = window_stats(state.window)
    sent, received = window_counts(state.window)
    if loss is not None and loss >= rules.loss_warn_pct and sent - received >= MIN_LOST_ECHOES:
        return f"packet loss {loss:.1f}% over the last {len(state.window)} cycles (warning threshold {rules.loss_warn_pct:g}%)"
    if avg is not None and avg >= rules.latency_warn_ms:
        return f"average latency {avg:.0f} ms over the last {len(state.window)} cycles (warning threshold {rules.latency_warn_ms:g} ms)"
    return None


def step(
    state: HealthState,
    result: ProbeResult,
    rules: Rules,
    upstream_offline: tuple[str, str] | None,
    now: datetime,
) -> Transition | None:
    """Apply one probe cycle to `state` (mutated in place). Returns a Transition if the status changed.

    `upstream_offline` is (id, name) of the nearest-to-the-monitor device on the path to this
    device that is currently OFFLINE, or None.
    """
    if not result.ok:
        return None

    old = state.status
    window = deque(state.window, maxlen=rules.window_cycles)
    window.append(
        CycleSample(result.sent, result.received, float(sum(result.rtts_ms)), len(result.rtts_ms))
    )
    state.window = window

    new = old
    reason = ""
    caused_by: str | None = state.caused_by

    if result.received > 0:
        state.last_seen = now
        state.consecutive_failures = 0
        state.consecutive_successes += 1
        if old in DOWN_STATES:
            if state.consecutive_successes >= rules.recovery_confirmations:
                state.window = deque([window[-1]], maxlen=rules.window_cycles)  # old data belongs to the outage
                new, caused_by = S.ONLINE.value, None
                reason = f"recovered: replies in {state.consecutive_successes} consecutive probe cycles"
        else:
            degraded = _degraded_reason(state, rules)
            if degraded:
                new, reason = S.DEGRADED.value, degraded
            else:
                new = S.ONLINE.value
                reason = "first successful probe" if old == S.UNKNOWN.value else "metrics back below warning thresholds"
            caused_by = None
    else:
        state.consecutive_failures += 1
        state.consecutive_successes = 0
        if state.consecutive_failures >= rules.failure_confirmations:
            if upstream_offline is not None:
                new, caused_by = S.UNREACHABLE.value, upstream_offline[0]
                reason = f"no reply for {state.consecutive_failures} consecutive cycles; upstream device {upstream_offline[1]} is offline"
            else:
                new, caused_by = S.OFFLINE.value, None
                reason = f"no reply for {state.consecutive_failures} consecutive probe cycles"

    state.status = new
    state.caused_by = caused_by if new == S.UNREACHABLE.value else None
    if new in UP_STATES and old not in UP_STATES:
        state.up_since = now
    elif new in DOWN_STATES:
        state.up_since = None

    if new != old:
        return Transition(old, new, reason, state.caused_by)
    return None
