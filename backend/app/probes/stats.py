"""RTT statistics and packet-loss maths shared by every probe.

Both the real and the simulated probe feed their raw numbers through these
functions, so a REAL and a SIMULATED measurement are computed identically.
"""
from collections.abc import Sequence


def packet_loss_pct(sent: int, received: int) -> float:
    """loss % = (sent - received) / sent x 100."""
    if sent <= 0:
        raise ValueError("sent must be positive to compute packet loss")
    if not 0 <= received <= sent:
        raise ValueError("received must be between 0 and sent")
    return (sent - received) / sent * 100.0


def jitter_ms(rtts: Sequence[float]) -> float | None:
    """Mean absolute difference between consecutive RTTs (in arrival order).

    Needs at least two replies. This is a simple, explainable definition of
    jitter (delay variation). RFC 3550 uses a smoothed estimator and Linux
    `ping` prints `mdev` (standard deviation); those are different numbers.
    """
    if len(rtts) < 2:
        return None
    diffs = [abs(b - a) for a, b in zip(rtts, rtts[1:])]
    return sum(diffs) / len(diffs)
