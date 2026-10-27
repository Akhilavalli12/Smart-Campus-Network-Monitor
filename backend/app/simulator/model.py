"""Educational model of how network faults change what a probe observes.

This is NOT a physical network simulator. It captures four ideas:
  1. a healthy path has a baseline RTT with random variation and rare spikes;
  2. a device can be offline (no packet gets through);
  3. a path can add delay or lose packets;
  4. congestion makes queues grow, which raises delay first and then causes loss.

All numbers are SIMULATED. The queueing formula is a deliberate simplification.
"""
from collections.abc import Sequence
from dataclasses import dataclass

from app.network_model.enums import FaultType, MonitoringMode
from app.network_model.models import Device

# Defaults used when an injected fault carries no explicit parameter.
DEFAULT_HIGH_LATENCY_RTT_MS = 180.0
DEFAULT_PACKET_LOSS_PCT = 12.0
DEFAULT_CONGESTION_UTILIZATION_PCT = 95.0

# Congestion model (simplified single-queue approximation, M/M/1-like):
#   extra delay = service_time * rho / (1 - rho)        rho = utilization / 100, capped at 0.99
#   loss        = 0 below 90 % utilization, rising linearly to MAX_CONGESTION_LOSS at 100 %
CONGESTION_RHO_CAP = 0.99
CONGESTION_LOSS_ONSET = 0.90
MAX_CONGESTION_LOSS = 0.15
DEFAULT_BASE_RTT_MS = 5.0


@dataclass(frozen=True)
class SimulatorConfig:
    seed: int = 42
    jitter_ratio: float = 0.10  # standard deviation of RTT noise as a fraction of the mean RTT
    spike_probability: float = 0.005  # chance that one echo is hit by a random latency spike
    spike_multiplier: tuple[float, float] = (3.0, 8.0)  # spike adds base_rtt x U(low, high)
    baseline_loss_probability: float = 0.002  # healthy-path loss (0.2 %)
    service_time_ms: float = 4.0  # per-packet service time in the congestion formula


@dataclass(frozen=True)
class FaultEffect:
    offline: bool = False
    extra_latency_ms: float = 0.0
    loss_probability: float = 0.0


NO_EFFECT = FaultEffect()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def congestion_effect(utilization_pct: float, config: SimulatorConfig) -> FaultEffect:
    rho = _clamp(utilization_pct / 100.0, 0.0, CONGESTION_RHO_CAP)
    extra = config.service_time_ms * rho / (1.0 - rho)
    if rho <= CONGESTION_LOSS_ONSET:
        loss = 0.0
    else:
        loss = (rho - CONGESTION_LOSS_ONSET) / (1.0 - CONGESTION_LOSS_ONSET) * MAX_CONGESTION_LOSS
    return FaultEffect(extra_latency_ms=extra, loss_probability=loss)


def effect_of(device: Device, config: SimulatorConfig) -> FaultEffect:
    """What the injected fault on `device` does to any probe that passes through or ends at it."""
    if device.monitoring_mode != MonitoringMode.SIMULATED:
        return NO_EFFECT  # a real device cannot carry simulated faults
    fault = device.sim_state.fault
    params = device.sim_state.params
    base = device.base_rtt_ms or DEFAULT_BASE_RTT_MS

    if fault == FaultType.OFFLINE:
        return FaultEffect(offline=True)
    if fault == FaultType.HIGH_LATENCY:
        target_rtt = _clamp(params.get("rtt_ms", DEFAULT_HIGH_LATENCY_RTT_MS), 0.0, 10_000.0)
        return FaultEffect(extra_latency_ms=max(0.0, target_rtt - base))
    if fault == FaultType.PACKET_LOSS:
        loss_pct = _clamp(params.get("loss_pct", DEFAULT_PACKET_LOSS_PCT), 0.0, 100.0)
        return FaultEffect(loss_probability=loss_pct / 100.0)
    if fault == FaultType.CONGESTION:
        return congestion_effect(params.get("utilization_pct", DEFAULT_CONGESTION_UTILIZATION_PCT), config)
    return NO_EFFECT


def combine_path(effects: Sequence[FaultEffect], baseline_loss: float) -> FaultEffect:
    """Merge the effects of every device on the path.

    Offline anywhere on the path -> nothing arrives. Delays add up. Independent
    per-hop loss compounds: P(delivered) = product of (1 - p_i).
    """
    delivered = 1.0 - baseline_loss
    extra = 0.0
    offline = False
    for effect in effects:
        offline = offline or effect.offline
        extra += effect.extra_latency_ms
        delivered *= 1.0 - effect.loss_probability
    return FaultEffect(offline=offline, extra_latency_ms=extra, loss_probability=1.0 - delivered)
