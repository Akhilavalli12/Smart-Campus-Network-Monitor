"""The traffic pipeline: simulated counters -> rates -> samples/link readings -> aggregation."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.config.settings import Settings
from app.monitoring.models import Thresholds
from app.network_model.seed import seed_database
from app.simulator.faults import set_fault
from app.simulator.traffic import SimulatedTraffic, TrafficModelConfig
from app.traffic import aggregate
from app.traffic.counters import CounterReading
from app.traffic.engine import TrafficEngine
from app.traffic.host import HostNicError, HostReading
from tests.fakes import InMemoryNetworkStore, InMemoryTrafficStore

CONFIG = TrafficModelConfig(seed=3, diurnal_amplitude=0.0, noise_sd=0.0)
SETTINGS = Settings(_env_file=None)


class Clock:
    """Advances 5 s per call. `recent=True` starts 25 minutes ago so history queries ('last hour') include the samples."""

    def __init__(self, recent=False):
        self.now = datetime.now(timezone.utc) - timedelta(minutes=25) if recent else datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.now += timedelta(seconds=5)
        return self.now


class ScriptedHost:
    """Pretends to be the host NIC: 10 Mbit/s down, 2 Mbit/s up, every 5 s."""

    def __init__(self, fail=None, label="eth0", speed=100.0):
        self.fail, self.label, self.speed, self.calls = fail, label, speed, 0

    def read(self):
        if self.fail:
            raise self.fail
        self.calls += 1
        n = self.calls
        return HostReading(self.label, (self.label,), CounterReading(rx_bytes=n * 6_250_000, tx_bytes=n * 1_250_000, rx_packets=n * 5000, tx_packets=n * 1000, bits=64), self.speed)


class Rig:
    def __init__(self, host=None, config=CONFIG):
        self.network, self.traffic = InMemoryNetworkStore(), InMemoryTrafficStore()
        asyncio.run(seed_database(self.network))
        self.sim = SimulatedTraffic(config)
        self.engine = TrafficEngine(self.network, self.traffic, self.sim, host, SETTINGS, clock=Clock())

    def cycles(self, n=1):
        report = None
        for _ in range(n):
            report = asyncio.run(self.engine.run_cycle())
        return report

    def fault(self, device_id, fault, **params):
        asyncio.run(set_fault(self.network, device_id, fault, params))

    def link(self, link_id):
        return self.network.links[link_id]

    def samples(self, scope="link", ref=None):
        return [s for s in self.traffic.samples if s.scope == scope and (ref is None or s.ref_id == ref)]


def test_the_first_cycle_only_records_counters_then_samples_follow():
    r = Rig()
    first = r.cycles(1)
    assert first.samples == [] and r.link("core-switch--cse-switch").latest is None  # one reading is not a rate
    second = r.cycles(1)
    assert len(second.samples) == 16 and second.discarded == 0
    assert r.link("core-switch--cse-switch").latest is not None


def test_stored_rates_equal_the_simulated_rates_through_the_counter_round_trip():
    r = Rig()
    r.cycles(3)
    for link in r.network.links.values():
        latest = link.latest
        expected = r.sim.rates[link.id]
        assert latest.rx_mbps == pytest.approx(expected.down_mbps, rel=0.01, abs=0.001)
        assert latest.tx_mbps == pytest.approx(expected.up_mbps, rel=0.01, abs=0.001)
        assert latest.source == "simulated"
        assert latest.util_pct == pytest.approx(max(latest.rx_mbps, latest.tx_mbps) / link.capacity_mbps * 100)


def test_samples_keep_the_raw_counters_and_a_protocol_split():
    r = Rig()
    r.cycles(3)
    sample = r.samples(ref="core-switch--cse-switch")[-1]
    assert sample.dt_s == pytest.approx(5.0) and sample.capacity_mbps == 100
    assert sample.rx_bytes < 2**32 and sample.rx_packets > 0  # 32-bit simulated counters
    assert set(sample.proto_bytes) == {"tcp", "udp", "dns", "icmp", "other"}
    total = sample.rx_mbps * 1e6 / 8 * 5 + sample.tx_mbps * 1e6 / 8 * 5
    assert sum(sample.proto_bytes.values()) == pytest.approx(total, rel=0.01)


def test_wrapping_counters_never_produce_a_gap_or_a_fake_burst():
    r = Rig()
    r.cycles(420)  # 35 simulated minutes: the 32-bit counters of busy links wrap several times
    wan = r.samples(ref="internet--edge-router")
    assert len(wan) == 419  # one sample per cycle after the first: no cycle was discarded
    assert any(s.wrapped for s in wan)
    rates = [s.rx_mbps for s in wan]
    assert max(rates) - min(rates) < 0.01 * max(rates)  # flat model: the rate is steady across every wrap


def test_a_counter_reset_is_discarded_not_reported_as_traffic():
    r = Rig()
    r.cycles(3)
    key = ("link", "core-switch--cse-switch")
    when, reading = r.engine._previous[key]
    r.engine._previous[key] = (when, CounterReading(rx_bytes=4_000_000_000, tx_bytes=4_000_000_000, rx_packets=4_000_000_000, tx_packets=4_000_000_000, bits=32))
    report = r.cycles(1)
    assert report.discarded == 1
    assert not any(s.ref_id == "core-switch--cse-switch" and s.ts == r.engine.status.last_cycle_at for s in report.samples)
    assert r.cycles(1).discarded == 0  # recovers on the next cycle


def test_congestion_fault_shows_up_as_high_utilization_and_a_congested_link():
    r = Rig()
    r.cycles(2)
    r.fault("cse-switch", "congestion", utilization_pct=95)
    r.cycles(2)
    link = r.link("core-switch--cse-switch")
    assert link.latest.util_pct == pytest.approx(95.0, abs=0.5)
    by_id = {d.id: d for d in r.network.devices.values()}
    assert aggregate.link_state(link, by_id, Thresholds()) == "congested"
    assert aggregate.link_state(r.link("core-switch--library-switch"), by_id, Thresholds()) == "up"


def test_offline_device_link_goes_quiet_and_is_reported_down_once_the_monitor_confirms():
    r = Rig()
    r.cycles(2)
    r.fault("cse-switch", "offline")
    r.cycles(2)
    link = r.link("core-switch--cse-switch")
    assert link.latest.rx_mbps == 0 and link.latest.tx_mbps == 0 and link.latest.util_pct == 0
    by_id = {d.id: d for d in r.network.devices.values()}
    assert aggregate.link_state(link, by_id, Thresholds()) == "up"  # traffic stopped, but nobody has declared the device down yet
    asyncio.run(r.network.update_device_fields("cse-switch", {"status": "offline"}))
    by_id = {d.id: d for d in r.network.devices.values()}
    assert aggregate.link_state(link, by_id, Thresholds()) == "down"


def test_summary_by_block_matches_the_uplinks():
    r = Rig()
    r.cycles(3)
    links, devices = list(r.network.links.values()), list(r.network.devices.values())
    summary = aggregate.summarize(links, devices, Thresholds())
    blocks = {b.block: b for b in summary.blocks}
    assert set(blocks) == {"cse", "library", "admin"} and all(b.source == "simulated" for b in blocks.values())
    cse = r.link("core-switch--cse-switch").latest
    assert blocks["cse"].rx_mbps == pytest.approx(cse.rx_mbps) and blocks["cse"].total_mbps == pytest.approx(cse.rx_mbps + cse.tx_mbps)
    assert blocks["cse"].capacity_mbps == 100 and blocks["cse"].util_pct == pytest.approx(cse.util_pct)
    assert summary.campus_total_mbps == pytest.approx(sum(b.total_mbps for b in blocks.values()))
    assert all(b.state == "up" for b in blocks.values())
    assert summary.wan.kind == "wan" and summary.backbone.kind == "backbone"
    assert summary.busiest_link.util_pct == max(l.latest.util_pct for l in links if l.latest)
    assert summary.host is None


def test_before_any_data_the_summary_is_empty_not_an_error():
    r = Rig()
    summary = aggregate.summarize(list(r.network.links.values()), list(r.network.devices.values()), Thresholds())
    assert summary.blocks == [] and summary.busiest_link is None and summary.as_of is None and summary.campus_total_mbps == 0


# ---------- REAL host counters ----------
def test_host_nic_traffic_is_computed_from_real_counter_differences():
    r = Rig(host=ScriptedHost())
    r.cycles(3)
    samples = r.samples("host")
    assert len(samples) == 2
    s = samples[-1]
    assert (s.source, s.label, s.ref_id) == ("real", "eth0", "host")
    assert s.rx_mbps == pytest.approx(10.0) and s.tx_mbps == pytest.approx(2.0)
    assert s.rx_pps == pytest.approx(1000.0) and s.util_pct == pytest.approx(10.0) and s.capacity_mbps == 100
    assert s.proto_bytes is None  # no protocol analysis of real traffic
    assert all(x.source == "simulated" for x in r.samples("link"))


def test_unknown_nic_speed_means_no_utilization():
    r = Rig(host=ScriptedHost(speed=None))
    r.cycles(3)
    assert r.samples("host")[-1].util_pct is None and r.samples("host")[-1].capacity_mbps is None


def test_a_failing_host_read_never_disturbs_the_campus_numbers():
    r = Rig(host=ScriptedHost(fail=HostNicError("interface 'x' not found")))
    report = r.cycles(3)
    assert "not found" in r.engine.host_error and report.host_error
    assert r.samples("host") == [] and len(r.samples("link")) == 32
    assert r.engine.status.cycles_completed == 3


def test_host_counter_reset_is_discarded():
    class Resetting(ScriptedHost):
        def read(self):
            reading = super().read()
            if self.calls == 3:  # the OS counters restart from zero
                return HostReading(reading.label, reading.interfaces, CounterReading(10, 10, 1, 1, 64), reading.speed_mbps)
            return reading

    r = Rig(host=Resetting())
    reports = [r.cycles(1) for _ in range(4)]
    assert reports[2].discarded == 1
    assert len(r.samples("host")) == 2  # cycles 2 and 4; the reset cycle produced nothing


def test_removed_links_are_forgotten():
    r = Rig()
    r.cycles(2)
    asyncio.run(r.network.delete_device("cse-pc-3"))
    asyncio.run(r.network.delete_links_of_device("cse-pc-3"))
    r.cycles(1)
    assert ("link", "cse-switch--cse-pc-3") not in r.engine._previous


def test_an_empty_network_is_not_an_error():
    r = Rig()
    r.network.links.clear()
    r.network.devices.clear()
    assert r.cycles(2).samples == []


# ---------- aggregation helpers ----------
def test_protocol_distribution_adds_up_and_is_labelled_simulated():
    r = Rig()
    r.cycles(5)
    uplinks = [l.id for ls in aggregate.block_uplinks(list(r.network.links.values()), list(r.network.devices.values())).values() for l in ls]
    samples = [s for s in r.samples() if s.ref_id in uplinks]
    dist = aggregate.protocol_distribution(samples, 5)
    assert dist.source == "simulated" and "No packets" in dist.note
    assert [p.name for p in dist.protocols] == ["tcp", "udp", "dns", "icmp", "other"]
    assert sum(p.pct for p in dist.protocols) == pytest.approx(100.0)
    assert dist.protocols[0].pct > 50  # TCP dominates
    assert aggregate.protocol_distribution([], 5).total_bytes == 0


def test_bucketing_averages_samples():
    r = Rig()
    r.cycles(14)
    raw = aggregate.series(r.samples(ref="internet--edge-router"))
    bucketed = aggregate.series(r.samples(ref="internet--edge-router"), bucket_s=30)
    assert len(raw) == 13 and 2 <= len(bucketed) <= 4
    assert bucketed[0].rx_mbps == pytest.approx(raw[0].rx_mbps, rel=0.05)  # flat model: averaging keeps the level


def test_block_series_sums_a_blocks_links_per_cycle():
    r = Rig()
    r.cycles(4)
    mapping = {l.id: b for b, ls in aggregate.block_uplinks(list(r.network.links.values()), list(r.network.devices.values())).items() for l in ls}
    points = aggregate.blocks_series(r.samples(), mapping, bucket_s=0)
    assert len(points) == 3 and set(points[0].blocks) == {"cse", "library", "admin"}
    assert points[0].blocks["cse"]["total_mbps"] == pytest.approx(points[0].blocks["cse"]["rx_mbps"] + points[0].blocks["cse"]["tx_mbps"])
    assert points == sorted(points, key=lambda p: p.ts)


def test_block_state_follows_the_configured_thresholds():
    r = Rig()
    r.cycles(3)
    links, devices = list(r.network.links.values()), list(r.network.devices.values())
    cse_util = r.link("core-switch--cse-switch").latest.util_pct
    strict = Thresholds(util_warn_pct=cse_util / 2, util_crit_pct=cse_util * 0.9)  # thresholds are configuration, not standards
    blocks = {b.block: b for b in aggregate.summarize(links, devices, strict).blocks}
    assert blocks["cse"].state == "congested"
    assert blocks["admin"].state == "up"
    assert aggregate.util_state(None, Thresholds()) == "unknown"
    assert aggregate.util_state(85, Thresholds()) == "busy" and aggregate.util_state(95, Thresholds()) == "congested"
