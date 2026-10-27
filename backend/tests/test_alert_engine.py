"""Scenario tests for the alert engine on top of the monitoring + traffic engines."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.alerts.engine import AlertEngine
from app.network_model.errors import InvalidNetworkData
from app.simulator.traffic import SimulatedTraffic
from app.traffic.engine import TrafficEngine
from tests.fakes import InMemoryAlertStore
from tests.test_engine import CLEAN, SETTINGS, Rig
from tests.test_traffic_engine import CONFIG as TRAFFIC_CONFIG


class AlertRig(Rig):
    def __init__(self):
        super().__init__()
        self.alert_store = InMemoryAlertStore()
        self.traffic = TrafficEngine(self.network, __import__("tests.fakes", fromlist=["x"]).InMemoryTrafficStore(), SimulatedTraffic(TRAFFIC_CONFIG), None, SETTINGS,
                                     clock=self.engine._clock)
        self.alerts = AlertEngine(self.network, self.alert_store, self.monitoring, SETTINGS, clock=self.engine._clock)

    def step(self, n=1):
        for _ in range(n):
            asyncio.run(self.engine.run_cycle())
            asyncio.run(self.traffic.run_cycle())
            return_value = asyncio.run(self.alerts.run_cycle())
        return return_value

    def all(self):
        return sorted(self.alert_store.alerts.values(), key=lambda a: a.opened_at)

    def open(self):
        return [a for a in self.all() if a.state == "open"]


@pytest.fixture
def rig():
    r = AlertRig()
    r.step(6)  # healthy baseline: windows full, traffic flowing
    return r


def test_a_healthy_network_raises_no_alerts(rig):
    rig.step(15)
    assert rig.all() == []


def test_switch_failure_raises_exactly_one_alert_naming_the_root_cause(rig):
    rig.fault("cse-switch", "offline")
    rig.step(6)
    alerts = rig.open()
    assert [(a.type, a.severity, a.device_id) for a in alerts] == [("DEVICE_OFFLINE", "critical", "cse-switch")]
    assert sorted(alerts[0].affected_device_ids) == ["cse-ap", "cse-pc-1", "cse-pc-2", "cse-pc-3", "cse-server"]
    assert "CSE Switch is unreachable" in alerts[0].message and "Packet loss: 100%" in alerts[0].message


def test_the_alert_is_deduplicated_while_the_fault_lasts(rig):
    rig.fault("cse-pc-1", "offline")
    rig.step(4)
    first = rig.open()[0]
    rig.step(20)
    assert len(rig.all()) == 1 and rig.open()[0].id == first.id  # same alert, never a second one
    assert rig.open()[0].updated_at > first.updated_at


def test_alert_resolves_automatically_on_recovery(rig):
    rig.fault("cse-switch", "offline")
    rig.step(5)
    assert len(rig.open()) == 1
    rig.clear("cse-switch")
    rig.step(4)
    assert rig.open() == [] and rig.all()[0].state == "resolved" and rig.all()[0].resolved_at is not None
    assert rig.all()[0].metrics["peak"] == 100.0


def test_latency_fault_alert_then_clears_with_hysteresis(rig):
    rig.fault("library-ap", "high_latency", rtt_ms=300)
    rig.step(6)
    alert = rig.open()[0]
    assert (alert.type, alert.device_id) == ("HIGH_LATENCY", "library-ap") and alert.severity in ("warning", "critical")
    rig.clear("library-ap")
    rig.step(8)
    assert rig.open() == []
    assert alert.metrics["peak"] > 100


def test_loss_fault_raises_a_loss_alert(rig):
    rig.fault("cse-pc-2", "packet_loss", loss_pct=50)
    rig.step(6)
    assert [(a.type, a.device_id) for a in rig.open()] == [("HIGH_PACKET_LOSS", "cse-pc-2")]


def test_congestion_raises_a_utilization_alert_and_blames_the_right_link(rig):
    rig.fault("admin-switch", "congestion", utilization_pct=96)
    rig.step(8)
    kinds = {(a.type, a.device_id) for a in rig.open()}
    assert ("HIGH_UTILIZATION", "admin-switch") in kinds
    util = next(a for a in rig.open() if a.type == "HIGH_UTILIZATION")
    assert util.link_id == "core-switch--admin-switch" and util.severity == "critical" and "Admin Block network" in util.message
    assert all(d == "admin-switch" for _, d in kinds)  # nothing blamed on the healthy children behind it
    rig.clear("admin-switch")
    rig.step(10)
    assert rig.open() == []


def test_two_independent_failures_make_two_alerts(rig):
    rig.fault("cse-pc-1", "offline")
    rig.fault("library-switch", "offline")
    rig.step(6)
    assert sorted(a.device_id for a in rig.open()) == ["cse-pc-1", "library-switch"]


def test_core_failure_still_means_one_alert(rig):
    rig.fault("core-switch", "offline")
    rig.step(6)
    assert [(a.type, a.device_id) for a in rig.open()] == [("DEVICE_OFFLINE", "core-switch")]
    assert len(rig.open()[0].affected_device_ids) >= 14
