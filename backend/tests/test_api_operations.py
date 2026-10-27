"""API for alerts, fault simulation, the dashboard summary and chart-ready history."""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.alerts.engine import AlertEngine
from app.api.dependencies import get_alert_store, get_monitoring_store, get_store, get_traffic_store
from app.config import get_settings
from app.config.settings import Settings
from app.main import create_app
from app.monitoring.engine import MonitoringEngine
from app.network_model.seed import seed_database
from app.probes.dispatcher import ProbeDispatcher
from app.simulator import SimulatedProbe
from app.simulator.traffic import SimulatedTraffic
from app.traffic.engine import TrafficEngine
from tests.fakes import InMemoryAlertStore, InMemoryMonitoringStore, InMemoryNetworkStore, InMemoryTrafficStore
from tests.test_engine import CLEAN, SETTINGS, StubReal
from tests.test_traffic_engine import CONFIG as TCONFIG, Clock


@pytest.fixture
def ops():
    network, monitoring, traffic, alerts = InMemoryNetworkStore(), InMemoryMonitoringStore(), InMemoryTrafficStore(), InMemoryAlertStore()
    asyncio.run(seed_database(network))
    clock = Clock(recent=True)
    monitor = MonitoringEngine(network, monitoring, ProbeDispatcher(StubReal(), SimulatedProbe(CLEAN)), SETTINGS, clock=clock)
    traffic_engine = TrafficEngine(network, traffic, SimulatedTraffic(TCONFIG), None, SETTINGS, clock=clock)
    alert_engine = AlertEngine(network, alerts, monitoring, SETTINGS, clock=clock)
    app = create_app()
    app.dependency_overrides[get_store] = lambda: network
    app.dependency_overrides[get_monitoring_store] = lambda: monitoring
    app.dependency_overrides[get_traffic_store] = lambda: traffic
    app.dependency_overrides[get_alert_store] = lambda: alerts
    client = TestClient(app)
    client.__enter__()

    def step(n=1):
        for _ in range(n):
            asyncio.run(monitor.run_cycle())
            asyncio.run(traffic_engine.run_cycle())
            asyncio.run(alert_engine.run_cycle())

    client.step, client.app_ref = step, app
    step(6)
    yield client
    client.__exit__(None, None, None)


# ---------- simulation ----------
def test_simulation_state_lists_only_simulated_devices_and_scenarios(ops):
    body = ops.get("/api/simulation/state").json()
    assert body["enabled"] and len(body["devices"]) == 16 and "internet" not in {d["id"] for d in body["devices"]}
    assert body["active"] == []
    assert set(body["fault_catalog"]) == {"offline", "high_latency", "packet_loss", "congestion"}
    assert body["fault_catalog"]["packet_loss"] == {"loss_pct": [0.0, 100.0]}
    assert {s["id"] for s in body["scenarios"]} >= {"switch-failure", "congestion", "latency-spike"}


def test_inject_then_detect_then_alert_then_clear_then_recover(ops):
    injected = ops.post("/api/simulation/faults", json={"device_id": "cse-switch", "fault": "offline"})
    assert injected.status_code == 200 and injected.json()["fault"] == "offline"
    assert [d["id"] for d in ops.get("/api/simulation/state").json()["active"]] == ["cse-switch"]
    ops.step(5)
    assert ops.get("/api/devices/cse-switch").json()["status"] == "offline"
    assert ops.get("/api/devices/cse-pc-1").json()["status"] == "unreachable"
    alerts = ops.get("/api/alerts", params={"state": "open"}).json()
    assert [a["type"] for a in alerts] == ["DEVICE_OFFLINE"] and len(alerts[0]["affected_device_ids"]) == 5
    assert ops.get("/api/alerts/summary").json()["critical"] == 1
    assert ops.delete("/api/simulation/faults/cse-switch").status_code == 200
    ops.step(4)
    assert ops.get("/api/devices/cse-switch").json()["status"] == "online"
    assert ops.get("/api/alerts", params={"state": "open"}).json() == []
    assert len(ops.get("/api/alerts", params={"state": "resolved"}).json()) == 1


@pytest.mark.parametrize(
    "body,status",
    [
        ({"device_id": "internet", "fault": "offline"}, 422),  # real device
        ({"device_id": "ghost", "fault": "offline"}, 404),
        ({"device_id": "cse-pc-1", "fault": "meteor"}, 422),
        ({"device_id": "cse-pc-1", "fault": "packet_loss", "params": {"loss_pct": 500}}, 422),
        ({"device_id": "cse-pc-1", "fault": "offline", "params": {"rtt_ms": 5}}, 422),
        ({"device_id": "cse-pc-1", "fault": "offline", "extra": 1}, 422),
        ({"fault": "offline"}, 422),
    ],
)
def test_invalid_fault_requests_are_rejected(ops, body, status):
    assert ops.post("/api/simulation/faults", json=body).status_code == status
    assert ops.get("/api/simulation/state").json()["active"] == []


def test_scenario_clears_the_previous_faults_then_applies_its_own(ops):
    ops.post("/api/simulation/faults", json={"device_id": "cse-pc-3", "fault": "offline"})
    ran = ops.post("/api/simulation/scenarios/congestion/run").json()
    assert ran["applied"][0]["device_id"] == "admin-switch"
    assert [d["id"] for d in ops.get("/api/simulation/state").json()["active"]] == ["admin-switch"]
    assert ops.post("/api/simulation/scenarios/nope/run").status_code == 404
    assert ops.delete("/api/simulation/faults").json() == {"cleared_count": 1}
    assert ops.delete("/api/simulation/faults").json() == {"cleared_count": 0}


def test_every_scenario_is_valid_and_produces_its_expected_effect(ops):
    from app.simulator.scenarios import SCENARIOS

    for scenario in SCENARIOS:
        assert ops.post(f"/api/simulation/scenarios/{scenario.id}/run").status_code == 200, scenario.id
        ops.step(8)
        open_alerts = ops.get("/api/alerts", params={"state": "open"}).json()
        assert open_alerts, f"{scenario.id} produced no alert"
        ops.delete("/api/simulation/faults")
        ops.step(12)
        assert ops.get("/api/alerts", params={"state": "open"}).json() == [], f"{scenario.id} did not recover"


def test_fault_injection_can_be_switched_off():
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, simulation_enabled=False)
    app.dependency_overrides[get_store] = lambda: InMemoryNetworkStore()
    with TestClient(app) as client:
        assert client.post("/api/simulation/faults", json={"device_id": "x", "fault": "offline"}).status_code == 403
        assert client.delete("/api/simulation/faults").status_code == 403
        assert client.post("/api/simulation/scenarios/congestion/run").status_code == 403
        assert client.get("/api/simulation/state").json()["enabled"] is False


# ---------- alerts ----------
def test_alert_filters_acknowledge_and_404(ops):
    ops.post("/api/simulation/faults", json={"device_id": "cse-pc-1", "fault": "offline"})
    ops.post("/api/simulation/faults", json={"device_id": "library-ap", "fault": "high_latency", "params": {"rtt_ms": 300}})
    ops.step(7)
    everything = ops.get("/api/alerts").json()
    assert {a["type"] for a in everything} == {"DEVICE_OFFLINE", "HIGH_LATENCY"}
    assert [a["type"] for a in ops.get("/api/alerts", params={"type": "HIGH_LATENCY"}).json()] == ["HIGH_LATENCY"]
    assert ops.get("/api/alerts", params={"type": "NOPE"}).status_code == 422
    assert ops.get("/api/alerts", params={"state": "weird"}).status_code == 422
    summary = ops.get("/api/alerts/summary").json()
    assert summary["active"] == 2 and summary["unacknowledged"] == 2 and summary["by_type"]["DEVICE_OFFLINE"] == 1
    target = everything[0]["id"]
    acked = ops.post(f"/api/alerts/{target}/acknowledge").json()
    assert acked["acknowledged"] is True and acked["acknowledged_at"]
    assert ops.post(f"/api/alerts/{target}/acknowledge").json()["acknowledged_at"] == acked["acknowledged_at"]  # idempotent
    assert ops.get("/api/alerts/summary").json()["unacknowledged"] == 1
    assert ops.get(f"/api/alerts/{target}").json()["id"] == target
    assert ops.get("/api/alerts/ghost").status_code == 404 and ops.post("/api/alerts/ghost/acknowledge").status_code == 404


# ---------- dashboard ----------
def test_dashboard_summary_when_healthy(ops):
    body = ops.get("/api/dashboard/summary").json()
    assert body["devices"] == {"total": 17, "online": 17, "degraded": 0, "offline": 0, "unreachable": 0, "unknown": 0, "real": 1, "simulated": 16}
    assert body["active_alerts"] == 0 and 4 < body["avg_latency_ms"] < 20 and body["avg_packet_loss_pct"] == 0
    assert 0 < body["avg_utilization_pct"] < 100 and body["utilization_state"] == "up" and body["busiest_link_name"]
    assert body["demo_history_loaded_at"] is None


def test_dashboard_summary_during_an_outage(ops):
    ops.post("/api/simulation/scenarios/switch-failure/run")
    ops.step(6)
    body = ops.get("/api/dashboard/summary").json()
    assert (body["devices"]["offline"], body["devices"]["unreachable"], body["devices"]["online"]) == (1, 5, 11)
    assert body["active_alerts"] == 1 and body["critical_alerts"] == 1 and body["avg_packet_loss_pct"] > 20


# ---------- chart-ready history ----------
def test_device_history_raw_and_bucketed(ops):
    ops.step(20)
    raw = ops.get("/api/devices/cse-switch/history", params={"hours": 1}).json()
    assert len(raw) == 26 and {"ts", "rtt_avg_ms", "loss_pct", "jitter_ms", "status", "source"} <= set(raw[0])
    bucketed = ops.get("/api/devices/cse-switch/history", params={"hours": 1, "bucket_s": 3600}).json()
    assert len(bucketed) <= 2 and bucketed[0]["status"] == "online"
    assert ops.get("/api/devices/ghost/history").status_code == 404
    assert ops.get("/api/devices/cse-switch/history", params={"bucket_s": 99999}).status_code == 422


def test_buckets_keep_the_worst_status_so_short_outages_stay_visible(ops):
    ops.post("/api/simulation/faults", json={"device_id": "cse-pc-1", "fault": "offline"})
    ops.step(4)
    ops.delete("/api/simulation/faults/cse-pc-1")
    ops.step(6)
    one_bucket = ops.get("/api/devices/cse-pc-1/history", params={"bucket_s": 3600}).json()
    assert len(one_bucket) <= 2 and "offline" in {p["status"] for p in one_bucket}


def test_new_routes_return_503_when_the_database_is_down(down_client):
    for path in ("/api/alerts", "/api/alerts/summary", "/api/dashboard/summary", "/api/simulation/state", "/api/devices/cse-switch/history"):
        assert down_client.get(path).status_code == 503, path
