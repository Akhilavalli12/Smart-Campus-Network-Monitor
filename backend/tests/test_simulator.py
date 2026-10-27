import asyncio
import statistics

import pytest

from app.probes.base import ProbeSettings
from app.simulator import SimulatedProbe, SimulatorConfig, effect_of
from app.simulator.model import CONGESTION_LOSS_ONSET, congestion_effect
from tests.helpers import make_device

CONFIG = SimulatorConfig(seed=7)


def run(probe, device, count=5, upstream=()):
    return asyncio.run(probe.probe(device, ProbeSettings(count=count), upstream=upstream))


def test_healthy_device_matches_baseline_rtt():
    result = run(SimulatedProbe(CONFIG), make_device(base_rtt=8.0), count=3000)
    assert result.source == "simulated" and result.backend == "simulator"
    assert result.rtt_avg_ms == pytest.approx(8.0, rel=0.08)
    assert result.loss_pct < 1.0  # baseline loss is 0.2 %


def test_offline_fault_drops_everything():
    result = run(SimulatedProbe(CONFIG), make_device(fault="offline"), count=5)
    assert (result.sent, result.received, result.loss_pct) == (5, 0, 100.0)
    assert result.rtt_avg_ms is None and result.jitter_ms is None and not result.reachable


def test_high_latency_fault_targets_the_requested_rtt():
    default = run(SimulatedProbe(CONFIG), make_device(fault="high_latency"), count=2000)
    assert default.rtt_avg_ms == pytest.approx(180.0, rel=0.06)
    custom = run(SimulatedProbe(CONFIG), make_device(fault="high_latency", params={"rtt_ms": 400}), count=2000)
    assert custom.rtt_avg_ms == pytest.approx(400.0, rel=0.06)


def test_packet_loss_fault_loses_about_the_requested_share():
    result = run(SimulatedProbe(CONFIG), make_device(fault="packet_loss"), count=5000)
    assert result.loss_pct == pytest.approx(12.0, abs=1.8)
    result = run(SimulatedProbe(CONFIG), make_device(fault="packet_loss", params={"loss_pct": 50}), count=5000)
    assert result.loss_pct == pytest.approx(50.0, abs=3.0)


def test_congestion_raises_latency_and_causes_loss():
    result = run(SimulatedProbe(CONFIG), make_device(fault="congestion"), count=3000)  # default 95 % utilization
    assert result.rtt_avg_ms > 60  # base 8 ms + queueing delay
    assert 5.0 < result.loss_pct < 10.5  # about 7.5 % + baseline


def test_congestion_model_is_monotonic_and_loss_only_starts_near_saturation():
    utilizations = [0, 30, 60, 80, 90, 95, 99]
    delays = [congestion_effect(u, CONFIG).extra_latency_ms for u in utilizations]
    assert delays == sorted(delays) and delays[0] == 0
    assert congestion_effect(CONGESTION_LOSS_ONSET * 100, CONFIG).loss_probability == 0
    assert congestion_effect(95, CONFIG).loss_probability == pytest.approx(0.075)
    assert congestion_effect(300, CONFIG) == congestion_effect(99, CONFIG)  # utilization is capped


def test_fault_parameters_are_clamped():
    assert effect_of(make_device(fault="packet_loss", params={"loss_pct": 400}), CONFIG).loss_probability == 1.0
    assert effect_of(make_device(fault="packet_loss", params={"loss_pct": -5}), CONFIG).loss_probability == 0.0
    assert effect_of(make_device(fault="high_latency", params={"rtt_ms": 1}), CONFIG).extra_latency_ms == 0.0


def test_upstream_offline_makes_downstream_unreachable():
    switch = make_device("sw", fault="offline")
    pc = make_device("pc")  # healthy itself
    result = run(SimulatedProbe(CONFIG), pc, count=5, upstream=[switch])
    assert result.received == 0 and result.loss_pct == 100.0


def test_upstream_latency_adds_to_downstream_rtt():
    switch = make_device("sw", base_rtt=8, fault="high_latency", params={"rtt_ms": 108})  # +100 ms
    pc = make_device("pc", base_rtt=12)
    result = run(SimulatedProbe(CONFIG), pc, count=2000, upstream=[switch])
    assert result.rtt_avg_ms == pytest.approx(112.0, rel=0.06)


def test_upstream_loss_compounds():
    lossy_hop = make_device("sw", fault="packet_loss", params={"loss_pct": 50})
    lossy_pc = make_device("pc", fault="packet_loss", params={"loss_pct": 50})
    result = run(SimulatedProbe(CONFIG), lossy_pc, count=6000, upstream=[lossy_hop])
    assert result.loss_pct == pytest.approx(75.0, abs=3.0)  # 1 - 0.5 * 0.5


def test_real_devices_cannot_carry_simulated_faults():
    real_hop = make_device("r", mode="real", probe_target="1.1.1.1")
    real_hop = real_hop.model_copy(update={"sim_state": make_device(fault="offline").sim_state})
    result = run(SimulatedProbe(CONFIG), make_device("pc"), count=5, upstream=[real_hop])
    assert result.received > 0  # the stale fault on a real device is ignored


def test_simulated_probe_refuses_real_devices():
    result = run(SimulatedProbe(CONFIG), make_device(mode="real", probe_target="1.1.1.1"))
    assert not result.ok and "real-mode" in result.error


def test_same_seed_gives_identical_results_and_different_seed_differs():
    a = run(SimulatedProbe(SimulatorConfig(seed=1)), make_device(), count=50)
    b = run(SimulatedProbe(SimulatorConfig(seed=1)), make_device(), count=50)
    c = run(SimulatedProbe(SimulatorConfig(seed=2)), make_device(), count=50)
    assert a.rtts_ms == b.rtts_ms
    assert a.rtts_ms != c.rtts_ms


def test_devices_have_independent_random_streams():
    alone = SimulatedProbe(CONFIG)
    expected = run(alone, make_device("b"), count=20).rtts_ms
    busy = SimulatedProbe(CONFIG)
    run(busy, make_device("a"), count=20)  # probing another device first must not change b's numbers
    assert run(busy, make_device("b"), count=20).rtts_ms == expected


def test_injecting_a_fault_does_not_shift_later_samples():
    healthy = SimulatedProbe(CONFIG)
    run(healthy, make_device("x"), count=5)
    second_healthy = run(healthy, make_device("x"), count=5).rtts_ms

    faulted = SimulatedProbe(CONFIG)
    run(faulted, make_device("x", fault="offline"), count=5)  # cycle 1 fails
    second_after_fault = run(faulted, make_device("x"), count=5).rtts_ms  # cycle 2 healthy again
    assert second_after_fault == second_healthy


def test_successive_cycles_are_not_identical():
    probe = SimulatedProbe(CONFIG)
    first = run(probe, make_device(), count=5).rtts_ms
    second = run(probe, make_device(), count=5).rtts_ms
    assert first != second


def test_noise_has_expected_spread():
    result = run(SimulatedProbe(SimulatorConfig(seed=3, spike_probability=0)), make_device(base_rtt=100), count=4000)
    assert statistics.pstdev(result.rtts_ms) == pytest.approx(10.0, rel=0.15)  # jitter_ratio 0.10
