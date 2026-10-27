"""Scenario tests: the whole pipeline (faults -> probes -> state machine -> storage), without a database."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app.config.settings import Settings
from app.monitoring.engine import MonitoringEngine
from app.monitoring.models import MonitoringConfig, Thresholds
from app.network_model.errors import InvalidNetworkData
from app.network_model.seed import seed_database
from app.probes.base import ProbeResult
from app.probes.dispatcher import ProbeDispatcher
from app.simulator import SimulatedProbe, SimulatorConfig
from app.simulator.faults import set_fault
from tests.fakes import InMemoryMonitoringStore, InMemoryNetworkStore

CLEAN = SimulatorConfig(seed=11, spike_probability=0.0, baseline_loss_probability=0.0)  # removes random noise events
SETTINGS = Settings(_env_file=None)  # 3 failures, 2 recoveries, window 5, vantage core-switch

CSE_CHILDREN = {"cse-ap", "cse-server", "cse-pc-1", "cse-pc-2", "cse-pc-3"}


class StubReal:
    """Stands in for RealIcmpProbe so tests never touch the network."""

    def __init__(self, reachable=True):
        self.reachable = reachable

    async def probe(self, device, settings, *, upstream=()):
        received = settings.count if self.reachable else 0
        return ProbeResult(device.id, "real", device.probe_target or "", settings.count, received, tuple([12.0] * received), "stub")


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        self.now += timedelta(seconds=5)
        return self.now


class Rig:
    def __init__(self, prober=None, real_reachable=True, settings=SETTINGS):
        self.network = InMemoryNetworkStore()
        self.monitoring = InMemoryMonitoringStore()
        asyncio.run(seed_database(self.network))
        self.prober = prober or ProbeDispatcher(StubReal(real_reachable), SimulatedProbe(CLEAN))
        self.engine = MonitoringEngine(self.network, self.monitoring, self.prober, settings, clock=Clock())

    def cycles(self, n=1):
        report = None
        for _ in range(n):
            report = asyncio.run(self.engine.run_cycle())
        return report

    def fault(self, device_id, fault="offline", **params):
        asyncio.run(set_fault(self.network, device_id, fault, params))

    def clear(self, device_id):
        self.fault(device_id, "none")

    def status(self, device_id):
        return self.network.devices[device_id].status

    def statuses(self):
        return {d.id: d.status for d in self.network.devices.values()}

    def events(self):
        return list(self.monitoring.events)


@pytest.fixture
def rig():
    r = Rig()
    r.cycles(3)  # baseline: everything has been seen healthy
    r.baseline_events = len(r.monitoring.events)
    return r


def test_first_cycle_brings_every_device_online():
    r = Rig()
    report = r.cycles(1)
    assert report.probed == 17 and report.probe_errors == 0
    assert set(r.statuses().values()) == {"online"}
    assert len(r.monitoring.measurements) == 17
    assert len(r.events()) == 17 and all(e.from_status == "unknown" for e in r.events())


def test_device_documents_carry_the_latest_metrics(rig):
    switch = rig.network.devices["cse-switch"]
    assert switch.latest.source == "simulated" and switch.latest.sent == 5
    assert switch.latest.loss_pct == 0.0 and 4 < switch.latest.rtt_avg_ms < 16
    assert switch.last_seen is not None and switch.up_since is not None
    internet = rig.network.devices["internet"]
    assert internet.latest.source == "real" and internet.latest.backend == "stub"


def test_measurements_are_stored_per_cycle(rig):
    history = asyncio.run(rig.monitoring.list_measurements("cse-switch"))
    assert len(history) == 3 and all(m.status == "online" and m.error is None for m in history)
    assert history == sorted(history, key=lambda m: m.ts)


def test_healthy_network_stays_quiet(rig):
    rig.cycles(10)
    assert len(rig.monitoring.events) == rig.baseline_events  # no status flapping


# ---------- scenario 1: device failure ----------
def test_single_device_failure_is_confirmed_after_three_cycles(rig):
    rig.fault("cse-pc-1", "offline")
    rig.cycles(1)
    assert rig.status("cse-pc-1") == "online" and rig.network.devices["cse-pc-1"].consecutive_failures == 1
    rig.cycles(1)
    assert rig.status("cse-pc-1") == "online"
    rig.cycles(1)
    assert rig.status("cse-pc-1") == "offline"
    new = rig.events()[rig.baseline_events:]
    assert [(e.device_id, e.from_status, e.to_status) for e in new] == [("cse-pc-1", "online", "offline")]
    assert all(s == "online" for i, s in rig.statuses().items() if i != "cse-pc-1")


# ---------- scenario 2: upstream failure ----------
def test_switch_failure_yields_one_root_cause_and_unreachable_children(rig):
    rig.fault("cse-switch", "offline")
    rig.cycles(3)
    statuses = rig.statuses()
    assert statuses["cse-switch"] == "offline"
    assert {i for i, s in statuses.items() if s == "unreachable"} == CSE_CHILDREN
    assert all(rig.network.devices[i].caused_by == "cse-switch" for i in CSE_CHILDREN)
    assert rig.network.devices["cse-switch"].caused_by is None
    others = set(statuses) - CSE_CHILDREN - {"cse-switch"}
    assert all(statuses[i] == "online" for i in others)  # Library, Admin, backbone are untouched

    new = rig.events()[rig.baseline_events:]
    assert len(new) == 6
    assert [e.device_id for e in new if e.to_status == "offline"] == ["cse-switch"]  # exactly one root cause
    child_events = [e for e in new if e.to_status == "unreachable"]
    assert {e.device_id for e in child_events} == CSE_CHILDREN
    assert all(e.caused_by == "cse-switch" and "CSE Switch" in e.reason for e in child_events)


def test_core_switch_failure_isolates_everything_it_connects(rig):
    rig.fault("core-switch", "offline")
    rig.cycles(3)
    statuses = rig.statuses()
    assert statuses["core-switch"] == "offline"
    unreachable = {i for i, s in statuses.items() if s == "unreachable"}
    assert "edge-router" in unreachable and len(unreachable) == 15 - 0  # 15 devices depend on the core
    # Hybrid caveat: the REAL Internet probe still answered, and a real result cannot be overridden by the simulation.
    assert statuses["internet"] == "online"


def test_internet_outage_does_not_isolate_the_campus_lan():
    r = Rig(real_reachable=False)
    r.cycles(1)
    r.cycles(3)
    assert r.status("internet") == "offline"
    assert all(s == "online" for i, s in r.statuses().items() if i != "internet")


def test_recovery_clears_root_cause_and_children_together(rig):
    rig.fault("cse-switch", "offline")
    rig.cycles(3)
    events_before = len(rig.events())
    rig.clear("cse-switch")
    rig.cycles(1)
    assert rig.status("cse-switch") == "offline"  # one good cycle is not enough (recovery_confirmations = 2)
    rig.cycles(1)
    assert set(rig.statuses().values()) == {"online"}
    recovered = rig.events()[events_before:]
    assert len(recovered) == 6 and all(e.to_status == "online" and "recovered" in e.reason for e in recovered)
    assert all(rig.network.devices[i].caused_by is None for i in CSE_CHILDREN)


def test_child_with_its_own_fault_becomes_offline_when_the_switch_recovers(rig):
    rig.fault("cse-pc-2", "offline")
    rig.fault("cse-switch", "offline")
    rig.cycles(3)
    assert rig.status("cse-pc-2") == "unreachable"  # cannot tell yet: the switch hides it
    rig.clear("cse-switch")
    rig.cycles(2)
    assert rig.status("cse-switch") == "online"
    assert rig.status("cse-pc-2") == "offline"  # now its own fault is visible
    assert rig.status("cse-pc-1") == "online"


# ---------- scenarios 3-5: degraded ----------
def test_high_latency_degrades_then_recovers(rig):
    rig.fault("cse-ap", "high_latency", rtt_ms=180)
    rig.cycles(4)
    ap = rig.network.devices["cse-ap"]
    assert ap.status == "degraded" and ap.latest.window_rtt_avg_ms > 100
    assert "latency" in rig.events()[-1].reason
    rig.clear("cse-ap")
    rig.cycles(4)
    assert rig.status("cse-ap") == "online"


def test_packet_loss_degrades(rig):
    rig.fault("library-pc-1", "packet_loss", loss_pct=50)
    rig.cycles(4)
    pc = rig.network.devices["library-pc-1"]
    assert pc.status == "degraded" and pc.latest.window_loss_pct > 20
    assert "packet loss" in [e for e in rig.events() if e.device_id == "library-pc-1"][-1].reason


def test_congestion_degrades_on_latency_and_loss(rig):
    rig.fault("admin-switch", "congestion", utilization_pct=98)
    rig.cycles(4)
    switch = rig.network.devices["admin-switch"]
    assert switch.status == "degraded" and switch.latest.window_rtt_avg_ms > 100


def test_degraded_upstream_slows_children_without_changing_their_state_model(rig):
    rig.fault("cse-switch", "high_latency", rtt_ms=300)
    rig.cycles(4)
    assert rig.status("cse-switch") == "degraded"
    assert rig.status("cse-pc-1") == "degraded"  # their RTT really is high: delay accumulates along the path
    assert rig.status("library-pc-1") == "online"


# ---------- robustness ----------
def test_a_crashing_probe_is_isolated_from_the_rest_of_the_cycle():
    class Exploding(ProbeDispatcher):
        async def probe(self, device, settings, *, upstream=()):
            if device.id == "cse-pc-1":
                raise RuntimeError("driver bug")
            return await super().probe(device, settings, upstream=upstream)

    r = Rig(prober=Exploding(StubReal(), SimulatedProbe(CLEAN)))
    report = r.cycles(3)
    assert report.probe_errors == 1
    broken = r.network.devices["cse-pc-1"]
    assert broken.status == "unknown" and "driver bug" in broken.monitoring_error
    assert broken.consecutive_failures == 0
    assert sum(1 for s in r.statuses().values() if s == "online") == 16
    errors = [m for m in r.monitoring.measurements if m.error]
    assert len(errors) == 3 and all(m.device_id == "cse-pc-1" for m in errors)


def test_a_probe_timeout_is_reported_as_a_monitoring_error():
    class Hanging(ProbeDispatcher):
        async def probe(self, device, settings, *, upstream=()):
            if device.id == "admin-ap":
                raise asyncio.TimeoutError()
            return await super().probe(device, settings, upstream=upstream)

    r = Rig(prober=Hanging(StubReal(), SimulatedProbe(CLEAN)))
    r.cycles(1)
    assert "deadline" in r.network.devices["admin-ap"].monitoring_error


def test_monitoring_errors_do_not_turn_a_healthy_device_offline():
    broken = {"on": False}

    class Flaky(ProbeDispatcher):
        async def probe(self, device, settings, *, upstream=()):
            if broken["on"] and device.id == "cse-server":
                return ProbeResult(device.id, "simulated", "simulated", 0, 0, error="tool failure", backend="x")
            return await super().probe(device, settings, upstream=upstream)

    r = Rig(prober=Flaky(StubReal(), SimulatedProbe(CLEAN)))
    r.cycles(3)
    broken["on"] = True
    r.cycles(6)
    server = r.network.devices["cse-server"]
    assert server.status == "online" and server.monitoring_error == "tool failure"
    broken["on"] = False
    r.cycles(1)
    assert r.network.devices["cse-server"].monitoring_error is None


def test_runtime_configuration_applies_on_the_next_cycle(rig):
    asyncio.run(rig.monitoring.save_config(MonitoringConfig(failure_confirmations=1)))
    rig.fault("cse-pc-3", "offline")
    rig.cycles(1)
    assert rig.status("cse-pc-3") == "offline"  # one cycle was enough because the confirmation count is now 1


def test_changed_thresholds_change_what_counts_as_degraded(rig):
    asyncio.run(rig.monitoring.save_config(MonitoringConfig(thresholds=Thresholds(latency_warn_ms=30, latency_crit_ms=60))))
    rig.fault("cse-ap", "high_latency", rtt_ms=50)
    rig.cycles(5)
    assert rig.status("cse-ap") == "degraded"


def test_a_restarted_engine_resumes_from_persisted_state(rig):
    rig.fault("cse-pc-1", "offline")
    rig.cycles(3)
    assert rig.status("cse-pc-1") == "offline"
    events_before = len(rig.events())

    restarted = MonitoringEngine(rig.network, rig.monitoring, rig.prober, SETTINGS, clock=Clock())
    asyncio.run(restarted.run_cycle())
    assert len(rig.events()) == events_before  # no duplicate "offline" event after a restart
    rig.clear("cse-pc-1")
    asyncio.run(restarted.run_cycle())
    asyncio.run(restarted.run_cycle())
    assert rig.status("cse-pc-1") == "online"
    assert rig.events()[-1].to_status == "online"


def test_a_misconfigured_vantage_point_skips_the_cycle_instead_of_guessing():
    r = Rig(settings=Settings(_env_file=None, monitor_attached_to="no-such-device"))
    report = r.cycles(1)
    assert report.skipped_reason and "no-such-device" in report.skipped_reason
    assert r.monitoring.measurements == [] and "no-such-device" in r.engine.status.last_error


def test_an_empty_network_is_not_an_error():
    r = Rig()
    r.network.devices.clear()
    r.network.links.clear()
    assert r.cycles(1).skipped_reason == "no devices registered"


def test_devices_removed_between_cycles_are_forgotten(rig):
    asyncio.run(set_fault(rig.network, "cse-pc-3", "none"))
    asyncio.run(rig.network.delete_device("cse-pc-3"))
    asyncio.run(rig.network.delete_links_of_device("cse-pc-3"))
    report = rig.cycles(1)
    assert report.probed == 16 and "cse-pc-3" not in rig.engine._states


# ---------- the loop itself ----------
class FlakyNetwork(InMemoryNetworkStore):
    """Fails like a database outage for the first calls, then works."""

    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    async def list_devices(self, **kwargs):
        if self.failures > 0:
            self.failures -= 1
            raise ServerSelectionTimeoutError("MongoDB unreachable")
        return await super().list_devices(**kwargs)


async def _wait_for(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def test_the_loop_survives_a_database_outage_and_resumes():
    async def scenario():
        network, monitoring = FlakyNetwork(failures=0), InMemoryMonitoringStore()
        await seed_database(network)
        network.failures = 2  # the outage starts after seeding
        # model_construct skips validation so the test can use a very short poll interval
        await monitoring.save_config(MonitoringConfig.model_construct(
            poll_interval_s=0.05, failure_confirmations=3, recovery_confirmations=2, window_cycles=5, thresholds=Thresholds()))
        engine = MonitoringEngine(network, monitoring, ProbeDispatcher(StubReal(), SimulatedProbe(CLEAN)), SETTINGS)
        await engine.start()
        await _wait_for(lambda: engine.status.last_error is not None)  # outage observed
        assert "database unavailable" in engine.status.last_error
        await _wait_for(lambda: engine.status.cycles_completed >= 2)  # then it kept going
        assert engine.status.last_error is None and engine.status.running
        await engine.stop()
        assert not engine.status.running
        return network

    network = asyncio.run(scenario())
    assert all(d.status == "online" for d in network.devices.values())


def test_start_is_idempotent_and_stop_is_clean():
    async def scenario():
        network, monitoring = InMemoryNetworkStore(), InMemoryMonitoringStore()
        engine = MonitoringEngine(network, monitoring, ProbeDispatcher(StubReal(), SimulatedProbe(CLEAN)), SETTINGS)
        await engine.start()
        first = engine._task
        await engine.start()
        assert engine._task is first
        await engine.stop()
        await engine.stop()  # second stop must not raise

    asyncio.run(scenario())


def test_fault_service_rules():
    r = Rig()
    with pytest.raises(InvalidNetworkData, match="monitored for real"):
        asyncio.run(set_fault(r.network, "internet", "offline"))
    with pytest.raises(InvalidNetworkData, match="Unknown fault"):
        asyncio.run(set_fault(r.network, "cse-pc-1", "meteor"))
    with pytest.raises(InvalidNetworkData, match="does not take parameter"):
        asyncio.run(set_fault(r.network, "cse-pc-1", "offline", {"rtt_ms": 5}))
    with pytest.raises(InvalidNetworkData, match="between"):
        asyncio.run(set_fault(r.network, "cse-pc-1", "packet_loss", {"loss_pct": 140}))
    with pytest.raises(Exception, match="not found"):
        asyncio.run(set_fault(r.network, "ghost", "offline"))
