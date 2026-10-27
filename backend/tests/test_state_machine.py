from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring.state_machine import MIN_CYCLES_FOR_DEGRADED, HealthState, Rules, step, window_stats
from app.probes.base import ProbeResult

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
RULES = Rules(failure_confirmations=3, recovery_confirmations=2, window_cycles=5, latency_warn_ms=100, loss_warn_pct=5)


def good(rtt=10.0, sent=5, received=5):
    return ProbeResult("d", "simulated", "simulated", sent, received, tuple([rtt] * received), "simulator")


def dead(sent=5):
    return ProbeResult("d", "simulated", "simulated", sent, 0, (), "simulator")


def broken():
    return ProbeResult("d", "real", "1.1.1.1", 0, 0, error="no permission")


class Runner:
    """Feeds cycles into one device's state machine and remembers the transitions."""

    def __init__(self, rules=RULES, status="unknown"):
        self.state, self.rules, self.n, self.transitions = HealthState(status=status), rules, 0, []

    def feed(self, result, upstream_offline=None):
        self.n += 1
        t = step(self.state, result, self.rules, upstream_offline, T0 + timedelta(seconds=5 * self.n))
        if t:
            self.transitions.append(t)
        return t

    def feed_many(self, result, times, upstream_offline=None):
        for _ in range(times):
            self.feed(result, upstream_offline)

    @property
    def status(self):
        return self.state.status


def test_first_reply_makes_an_unknown_device_online():
    r = Runner()
    t = r.feed(good())
    assert (t.from_status, t.to_status) == ("unknown", "online")
    assert r.state.up_since is not None and r.state.last_seen is not None


def test_one_failed_cycle_never_marks_a_device_offline():
    r = Runner()
    r.feed(good())
    assert r.feed(dead()) is None
    assert r.status == "online" and r.state.consecutive_failures == 1


def test_offline_after_exactly_n_consecutive_failures():
    r = Runner()
    r.feed(good())
    r.feed_many(dead(), 2)
    assert r.status == "online" and r.state.consecutive_failures == 2
    t = r.feed(dead())
    assert (t.to_status, r.status) == ("offline", "offline")
    assert "3 consecutive" in t.reason
    assert r.state.up_since is None


def test_a_reply_resets_the_failure_counter():
    r = Runner()
    r.feed(good())
    r.feed_many(dead(), 2)
    r.feed(good())
    assert r.state.consecutive_failures == 0
    r.feed_many(dead(), 2)  # counting starts again from zero
    assert r.status != "offline"


def test_partial_loss_is_a_reply_cycle_not_a_failure():
    r = Runner()
    r.feed(good())
    r.feed_many(good(received=1), 5)  # 80 % loss, but the device keeps answering
    assert r.state.consecutive_failures == 0 and r.status != "offline"


def test_never_measured_device_needs_n_failures_before_offline():
    r = Runner()
    r.feed_many(dead(), 2)
    assert r.status == "unknown"
    r.feed(dead())
    assert r.status == "offline"


def test_recovery_needs_the_configured_number_of_good_cycles():
    r = Runner()
    r.feed(good())
    r.feed_many(dead(), 3)
    assert r.status == "offline"
    assert r.feed(good()) is None and r.status == "offline"  # 1 of 2
    t = r.feed(good())
    assert (t.from_status, t.to_status) == ("offline", "online")
    assert r.state.up_since is not None


def test_a_failure_during_recovery_restarts_the_count():
    r = Runner()
    r.feed(good())
    r.feed_many(dead(), 3)
    r.feed(good())
    r.feed(dead())
    r.feed(good())
    assert r.status == "offline"  # the single good cycle after the failure is only 1 of 2


def test_recovery_clears_the_outage_from_the_window():
    r = Runner()
    r.feed_many(good(), 3)
    r.feed_many(dead(), 3)
    r.feed_many(good(), 2)
    assert r.status == "online"
    loss, _ = window_stats(r.state.window)
    assert loss == 0.0  # old 100 % cycles were discarded, so no DEGRADED blip after recovery
    r.feed_many(good(), 3)
    assert r.status == "online"


def test_high_windowed_loss_degrades():
    r = Runner()
    r.feed_many(good(), 3)
    r.feed_many(good(received=2), 3)  # 60 % loss per cycle
    assert r.status == "degraded"
    assert "packet loss" in r.transitions[-1].reason


def test_high_windowed_latency_degrades_and_recovers():
    r = Runner()
    r.feed_many(good(10), 3)
    r.feed_many(good(180), 3)
    assert r.status == "degraded" and "latency" in r.transitions[-1].reason
    r.feed_many(good(10), 4)
    assert r.status == "online"


def test_one_lost_echo_does_not_flip_a_healthy_device():
    r = Runner()
    r.feed_many(good(), 4)
    r.feed(good(received=4))  # 1 of 25 echoes lost = 4 % < 5 % threshold
    assert r.status == "online"


def test_degradation_is_not_judged_before_enough_cycles():
    r = Runner()
    r.feed(good(received=4))  # first cycle has 20 % loss
    assert r.status == "online"
    assert MIN_CYCLES_FOR_DEGRADED == 3


def test_degraded_device_that_stops_answering_goes_offline():
    r = Runner()
    r.feed_many(good(received=2), 4)
    assert r.status == "degraded"
    r.feed_many(dead(), 3)
    assert r.status == "offline"


# ---------- upstream failure ----------
def test_failure_with_an_offline_upstream_is_unreachable_not_offline():
    r = Runner()
    r.feed(good())
    r.feed_many(dead(), 2, upstream_offline=("sw", "CSE Switch"))
    t = r.feed(dead(), upstream_offline=("sw", "CSE Switch"))
    assert (t.to_status, t.caused_by) == ("unreachable", "sw")
    assert "CSE Switch" in t.reason
    assert r.state.caused_by == "sw" and r.state.up_since is None


def test_unreachable_device_becomes_offline_if_upstream_recovers_but_it_stays_silent():
    r = Runner()
    r.feed(good())
    r.feed_many(dead(), 3, upstream_offline=("sw", "SW"))
    assert r.status == "unreachable"
    t = r.feed(dead(), upstream_offline=None)
    assert (t.from_status, t.to_status) == ("unreachable", "offline")
    assert r.state.caused_by is None


def test_offline_device_is_reclassified_when_an_upstream_later_fails():
    r = Runner()
    r.feed(good())
    r.feed_many(dead(), 3)
    assert r.status == "offline"
    t = r.feed(dead(), upstream_offline=("sw", "SW"))
    assert t.to_status == "unreachable"


def test_unreachable_device_recovers_when_replies_return():
    r = Runner()
    r.feed(good())
    r.feed_many(dead(), 3, upstream_offline=("sw", "SW"))
    r.feed(good())
    t = r.feed(good())
    assert (t.from_status, t.to_status) == ("unreachable", "online")
    assert r.state.caused_by is None


def test_upstream_offline_is_ignored_while_the_device_still_replies():
    r = Runner()
    r.feed(good())
    r.feed_many(good(), 3, upstream_offline=("sw", "SW"))  # e.g. a REAL device the simulator cannot affect
    assert r.status == "online"


# ---------- probe could not run ----------
def test_monitoring_errors_never_change_status_or_counters():
    r = Runner()
    r.feed(good())
    for _ in range(10):
        assert r.feed(broken()) is None
    assert r.status == "online" and r.state.consecutive_failures == 0


def test_monitoring_error_does_not_pollute_the_window():
    r = Runner()
    r.feed_many(good(), 3)
    r.feed_many(broken(), 5)
    loss, _ = window_stats(r.state.window)
    assert loss == 0.0 and len(r.state.window) == 3


# ---------- bookkeeping ----------
def test_up_since_is_kept_across_online_and_degraded():
    r = Runner()
    r.feed(good())
    first = r.state.up_since
    r.feed_many(good(received=2), 4)
    assert r.status == "degraded" and r.state.up_since == first


def test_last_seen_only_moves_on_replies():
    r = Runner()
    r.feed(good())
    seen = r.state.last_seen
    r.feed(dead())
    assert r.state.last_seen == seen


def test_window_is_bounded():
    r = Runner(rules=Rules(3, 2, 4, 100, 5))
    r.feed_many(good(), 10)
    assert len(r.state.window) == 4


def test_window_stats_values():
    r = Runner()
    r.feed(good(rtt=10, received=5))
    r.feed(good(rtt=30, received=3))
    loss, avg = window_stats(r.state.window)
    assert loss == pytest.approx(20.0)  # 2 of 10 echoes lost
    assert avg == pytest.approx((5 * 10 + 3 * 30) / 8)
