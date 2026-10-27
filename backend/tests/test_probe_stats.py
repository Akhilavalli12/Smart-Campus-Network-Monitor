import pytest

from app.probes.base import ProbeResult
from app.probes.stats import jitter_ms, packet_loss_pct


def test_packet_loss_formula_matches_the_spec_example():
    assert packet_loss_pct(100, 97) == pytest.approx(3.0)
    assert packet_loss_pct(5, 5) == 0.0
    assert packet_loss_pct(5, 0) == 100.0
    assert packet_loss_pct(4, 3) == pytest.approx(25.0)


@pytest.mark.parametrize("sent,received", [(0, 0), (-1, 0), (5, 6), (5, -1)])
def test_packet_loss_rejects_impossible_counts(sent, received):
    with pytest.raises(ValueError):
        packet_loss_pct(sent, received)


def test_jitter_is_mean_absolute_difference_of_consecutive_rtts():
    assert jitter_ms([10, 12, 11]) == pytest.approx(1.5)  # (|12-10| + |11-12|) / 2
    assert jitter_ms([5, 5, 5, 5]) == 0.0
    assert jitter_ms([10, 20]) == pytest.approx(10.0)


def test_jitter_needs_two_replies():
    assert jitter_ms([]) is None
    assert jitter_ms([7.0]) is None


def test_probe_result_derived_values():
    result = ProbeResult(device_id="d", source="real", target="1.1.1.1", sent=5, received=4, rtts_ms=(10.0, 12.0, 11.0, 15.0))
    assert result.ok and result.reachable
    assert result.loss_pct == pytest.approx(20.0)
    assert (result.rtt_min_ms, result.rtt_max_ms) == (10.0, 15.0)
    assert result.rtt_avg_ms == pytest.approx(12.0)
    assert result.jitter_ms == pytest.approx((2 + 1 + 4) / 3)


def test_total_loss_has_no_rtt_statistics():
    result = ProbeResult(device_id="d", source="real", target="1.1.1.1", sent=5, received=0)
    assert result.loss_pct == 100.0 and not result.reachable
    assert result.rtt_avg_ms is None and result.jitter_ms is None


def test_probe_error_is_not_packet_loss():
    result = ProbeResult(device_id="d", source="real", target="1.1.1.1", sent=0, received=0, error="no permission")
    assert not result.ok and not result.reachable
    assert result.loss_pct is None  # a broken tool must never read as "100% loss"
