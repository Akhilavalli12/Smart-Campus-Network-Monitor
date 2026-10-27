"""Interface-counter arithmetic: the method real network-management systems use.

A device exposes CUMULATIVE counters (bytes and packets sent/received since boot), as the
SNMP ifInOctets/ifOutOctets counters do. Throughput is never read directly; it is derived from
two readings:

    rate (bits/s) = (counter_now - counter_before) x 8 / seconds_between_readings
    utilization % = rate / link capacity x 100

Counters have a fixed width (32 or 64 bits) and wrap around to 0 when they overflow, so the
subtraction has to handle the wrap.
"""
from dataclasses import dataclass

# A measured rate above capacity x this factor is physically impossible (timing jitter aside),
# so after a wrap it is read as a counter RESET (device reboot), not as a real traffic burst.
RESET_PLAUSIBILITY_FACTOR = 1.25


@dataclass(frozen=True)
class CounterReading:
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    bits: int = 64  # width of the counters: they wrap at 2**bits


@dataclass(frozen=True)
class RateSample:
    dt_s: float
    rx_mbps: float
    tx_mbps: float
    rx_pps: float
    tx_pps: float
    util_pct: float | None
    wrapped: bool  # at least one counter wrapped between the two readings
    rx_bytes_delta: int
    tx_bytes_delta: int


def counter_delta(previous: int, current: int, bits: int) -> tuple[int, bool]:
    """Increase of a wrapping counter. Returns (delta, wrapped).

    current >= previous  -> plain difference.
    current <  previous  -> the counter overflowed once: delta = (2**bits - previous) + current.
    Limitation: if it wrapped TWICE between readings the extra lap is invisible, so the poll
    interval must be shorter than the wrap time (a 32-bit byte counter at 1 Gbit/s wraps every 34 s).
    """
    if current >= previous:
        return current - previous, False
    return (1 << bits) - previous + current, True


def compute_rate(
    previous: CounterReading, current: CounterReading, dt_s: float, capacity_mbps: float | None
) -> RateSample | None:
    """Rates between two readings, or None when no honest number can be produced.

    None is returned for: no elapsed time, differing counter widths, and a suspected counter reset.
    """
    if dt_s <= 0 or previous.bits != current.bits:
        return None
    bits = current.bits
    rx_b, rx_wrap = counter_delta(previous.rx_bytes, current.rx_bytes, bits)
    tx_b, tx_wrap = counter_delta(previous.tx_bytes, current.tx_bytes, bits)
    rx_p, rx_pwrap = counter_delta(previous.rx_packets, current.rx_packets, bits)
    tx_p, tx_pwrap = counter_delta(previous.tx_packets, current.tx_packets, bits)
    wrapped = rx_wrap or tx_wrap or rx_pwrap or tx_pwrap
    if wrapped and bits >= 64:
        return None  # a 64-bit counter takes decades to wrap, so a decrease means the counter was reset

    rx_mbps = rx_b * 8 / dt_s / 1e6
    tx_mbps = tx_b * 8 / dt_s / 1e6

    if wrapped and capacity_mbps is not None:
        limit = capacity_mbps * RESET_PLAUSIBILITY_FACTOR
        if rx_mbps > limit or tx_mbps > limit:
            return None  # an implausibly large "wrap" is a counter reset: discard instead of reporting a fake burst

    util = None if not capacity_mbps else max(rx_mbps, tx_mbps) / capacity_mbps * 100.0
    return RateSample(
        dt_s=dt_s,
        rx_mbps=rx_mbps,
        tx_mbps=tx_mbps,
        rx_pps=rx_p / dt_s,
        tx_pps=tx_p / dt_s,
        util_pct=util,
        wrapped=wrapped,
        rx_bytes_delta=rx_b,
        tx_bytes_delta=tx_b,
    )
