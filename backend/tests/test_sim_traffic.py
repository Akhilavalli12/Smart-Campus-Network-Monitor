from datetime import datetime, timedelta, timezone

import pytest

from app.network_model.seed import seed_database
from app.simulator.faults import set_fault
from app.simulator.traffic import PROTOCOLS, SimulatedTraffic, TrafficModelConfig, diurnal_factor
from app.traffic.counters import compute_rate
from tests.fakes import InMemoryNetworkStore
import asyncio

NOON = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)
FLAT = TrafficModelConfig(seed=5, diurnal_amplitude=0.0, noise_sd=0.0)  # no daily rhythm, no noise: exact sums


class Net:
    def __init__(self):
        self.store = InMemoryNetworkStore()
        asyncio.run(seed_database(self.store))

    @property
    def devices(self):
        return list(self.store.devices.values())

    @property
    def links(self):
        return list(self.store.links.values())

    def fault(self, device_id, fault, **params):
        asyncio.run(set_fault(self.store, device_id, fault, params))


def rates(net, config=FLAT, now=NOON, model=None):
    model = model or SimulatedTraffic(config)
    return model.compute_rates(net.devices, net.links, now), model


def test_block_uplink_carries_the_sum_of_its_devices():
    net = Net()
    r, _ = rates(net)
    kids = [l for l in net.links if l.a_id == "cse-switch"]
    assert len(kids) == 5
    assert r["core-switch--cse-switch"].down_mbps == pytest.approx(sum(r[k.id].down_mbps for k in kids))
    assert r["core-switch--cse-switch"].up_mbps == pytest.approx(sum(r[k.id].up_mbps for k in kids))


def test_backbone_is_the_sum_of_the_blocks_and_wan_is_a_share_of_it():
    net = Net()
    r, model = rates(net)
    blocks = [r[f"core-switch--{b}-switch"] for b in ("cse", "library", "admin")]
    backbone = r["edge-router--core-switch"]
    assert backbone.down_mbps == pytest.approx(sum(b.down_mbps for b in blocks))
    assert r["internet--edge-router"].down_mbps == pytest.approx(backbone.down_mbps * model.config.wan_fraction)


def test_typical_busy_hour_resembles_the_spec_example():
    net = Net()
    r, _ = rates(net, TrafficModelConfig(seed=5, noise_sd=0.0))  # default diurnal curve, at its daily peak (14:00 local)
    local_peak = datetime.now().astimezone().replace(hour=14, minute=0, second=0, microsecond=0)
    r = SimulatedTraffic(TrafficModelConfig(seed=5, noise_sd=0.0)).compute_rates(net.devices, net.links, local_peak)
    totals = {b: r[f"core-switch--{b}-switch"].down_mbps + r[f"core-switch--{b}-switch"].up_mbps for b in ("cse", "library", "admin")}
    assert totals["cse"] > totals["library"] > totals["admin"]
    assert 40 < totals["cse"] < 70 and 10 < totals["admin"] < 20  # same order of magnitude as 42 / 18 / 11 Mbit/s


def test_daily_rhythm():
    cfg = TrafficModelConfig(diurnal_amplitude=0.5, peak_hour=14.0)
    peak = datetime.now().astimezone().replace(hour=14, minute=0, second=0, microsecond=0)
    night = peak - timedelta(hours=12)
    assert diurnal_factor(peak, cfg) == pytest.approx(1.0)
    assert diurnal_factor(night, cfg) == pytest.approx(0.5)
    assert diurnal_factor(peak, TrafficModelConfig(diurnal_amplitude=0)) == 1.0


def test_no_link_exceeds_its_capacity():
    net = Net()
    net.fault("cse-pc-1", "congestion", utilization_pct=100)
    net.fault("cse-ap", "congestion", utilization_pct=100)
    net.fault("cse-server", "congestion", utilization_pct=100)
    r, _ = rates(net)
    for link in net.links:
        assert r[link.id].down_mbps <= link.capacity_mbps + 1e-9 and r[link.id].up_mbps <= link.capacity_mbps + 1e-9
    # three saturated access links overload the switch uplink, which therefore saturates at its capacity
    assert r["core-switch--cse-switch"].down_mbps == pytest.approx(100.0)


def test_congestion_fault_drives_the_uplink_to_the_requested_utilization():
    net = Net()
    net.fault("cse-switch", "congestion", utilization_pct=95)
    r, _ = rates(net)
    link = r["core-switch--cse-switch"]
    assert link.down_mbps == pytest.approx(95.0)  # 95 % of a 100 Mbit/s uplink
    assert link.up_mbps == pytest.approx(0.4 * 95.0)
    assert r["core-switch--library-switch"].down_mbps < 30  # other blocks unaffected


def test_offline_device_carries_nothing_and_cuts_off_what_is_behind_it():
    net = Net()
    healthy, _ = rates(net)
    net.fault("cse-switch", "offline")
    r, _ = rates(net)
    behind = [l for l in net.links if l.a_id == "cse-switch"] + [l for l in net.links if l.id == "core-switch--cse-switch"]
    assert all(r[l.id].down_mbps == 0 and r[l.id].up_mbps == 0 for l in behind)
    assert r["core-switch--library-switch"].down_mbps == pytest.approx(healthy["core-switch--library-switch"].down_mbps)
    assert r["edge-router--core-switch"].down_mbps < healthy["edge-router--core-switch"].down_mbps  # the backbone sees the loss


def test_offline_core_switch_silences_the_whole_campus():
    net = Net()
    net.fault("core-switch", "offline")
    r, _ = rates(net)
    assert all(rate.down_mbps == 0 and rate.up_mbps == 0 for rate in r.values())


def test_protocol_shares_sum_to_one_and_cover_all_protocols():
    net = Net()
    r, _ = rates(net, TrafficModelConfig(seed=5))
    for link_id, rate in r.items():
        assert set(rate.shares) == set(PROTOCOLS)
        assert sum(rate.shares.values()) == pytest.approx(1.0)
    server_link = r["cse-switch--cse-server"]
    pc_link = r["cse-switch--cse-pc-1"]
    assert server_link.shares["tcp"] > pc_link.shares["tcp"]  # a server is TCP-heavier than a PC


def test_same_seed_same_numbers_and_faults_do_not_shift_later_values():
    a, b = Net(), Net()
    ma, mb = SimulatedTraffic(TrafficModelConfig(seed=9)), SimulatedTraffic(TrafficModelConfig(seed=9))
    ra1, rb1 = ma.compute_rates(a.devices, a.links, NOON), mb.compute_rates(b.devices, b.links, NOON)
    assert ra1["cse-switch--cse-pc-1"] == rb1["cse-switch--cse-pc-1"]
    a.fault("library-pc-1", "offline")  # a fault on one leaf must not change the noise another leaf draws next
    ra2 = ma.compute_rates(a.devices, a.links, NOON + timedelta(seconds=5))
    rb2 = mb.compute_rates(b.devices, b.links, NOON + timedelta(seconds=5))
    assert ra2["cse-switch--cse-pc-1"] == rb2["cse-switch--cse-pc-1"]
    other = SimulatedTraffic(TrafficModelConfig(seed=10)).compute_rates(b.devices, b.links, NOON)
    assert other["cse-switch--cse-pc-1"] != rb1["cse-switch--cse-pc-1"]


# ---------- counters ----------
def test_first_read_has_no_elapsed_time_then_counters_advance_by_rate_x_time():
    net = Net()
    model = SimulatedTraffic(FLAT)
    first = model.read(net.devices, net.links, NOON)
    second = model.read(net.devices, net.links, NOON + timedelta(seconds=10))
    link = next(l for l in net.links if l.id == "core-switch--cse-switch")
    sample = compute_rate(first[link.id], second[link.id], 10.0, link.capacity_mbps)
    expected = model.rates[link.id]
    assert sample.rx_mbps == pytest.approx(expected.down_mbps, rel=1e-3)
    assert sample.tx_mbps == pytest.approx(expected.up_mbps, rel=1e-3)
    assert sample.rx_pps > 0 and sample.rx_pps == pytest.approx(sample.rx_mbps * 1e6 / 8 / 720, rel=0.3)  # about 720-byte packets


def test_counters_do_not_start_at_zero_and_are_32_bit_by_default():
    net = Net()
    first = SimulatedTraffic(FLAT).read(net.devices, net.links, NOON)
    values = [r.rx_bytes for r in first.values()]
    assert all(r.bits == 32 for r in first.values())
    assert all(0 <= v < 2**32 for v in values) and any(v > 0 for v in values)
    assert len(set(values)) > 1  # different offsets per link


def test_a_32_bit_counter_really_wraps_and_the_rate_stays_correct():
    net = Net()
    model = SimulatedTraffic(FLAT)
    link = next(l for l in net.links if l.id == "internet--edge-router")  # the busiest link
    prev, wraps = model.read(net.devices, net.links, NOON)[link.id], 0
    t = NOON
    for _ in range(400):  # 400 x 5 s = 33 simulated minutes: enough for several 4.29 GB wraps
        t += timedelta(seconds=5)
        cur = model.read(net.devices, net.links, t)[link.id]
        sample = compute_rate(prev, cur, 5.0, link.capacity_mbps)
        assert sample is not None, "a genuine wrap must never be mistaken for a reset"
        assert sample.rx_mbps == pytest.approx(model.rates[link.id].down_mbps, rel=0.01)
        wraps += sample.wrapped
        prev = cur
    assert wraps >= 1


def test_64_bit_counters_are_supported():
    net = Net()
    model = SimulatedTraffic(TrafficModelConfig(seed=5, counter_bits=64, diurnal_amplitude=0, noise_sd=0))
    first = model.read(net.devices, net.links, NOON)
    assert all(r.bits == 64 for r in first.values())
