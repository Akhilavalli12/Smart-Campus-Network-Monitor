import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_engine, get_monitoring_store, get_store
from app.config.settings import Settings
from app.main import create_app
from app.monitoring.engine import MonitoringEngine
from app.network_model.seed import seed_database
from app.probes.dispatcher import ProbeDispatcher
from app.simulator import SimulatedProbe, SimulatorConfig
from app.simulator.faults import set_fault
from tests.fakes import InMemoryMonitoringStore, InMemoryNetworkStore
from tests.test_engine import CLEAN, StubReal


@pytest.fixture
def monitored():
    """API wired to in-memory stores; the engine is driven by hand (no background loop)."""
    network, monitoring = InMemoryNetworkStore(), InMemoryMonitoringStore()
    asyncio.run(seed_database(network))
    engine = MonitoringEngine(network, monitoring, ProbeDispatcher(StubReal(), SimulatedProbe(CLEAN)), Settings(_env_file=None))
    app = create_app()
    app.dependency_overrides[get_store] = lambda: network
    app.dependency_overrides[get_monitoring_store] = lambda: monitoring
    app.dependency_overrides[get_engine] = lambda: engine
    client = TestClient(app)
    client.__enter__()
    client.cycles = lambda n=1: [asyncio.run(engine.run_cycle()) for _ in range(n)]
    client.fault = lambda device, fault, **params: asyncio.run(set_fault(network, device, fault, params))
    yield client
    client.__exit__(None, None, None)


def test_status_when_the_engine_is_disabled(seeded_client):
    body = seeded_client.get("/api/monitoring/status").json()
    assert body["enabled"] is False and body["running"] is False


def test_status_reports_cycles_and_worst_case_detection_time(monitored):
    monitored.cycles(2)
    body = monitored.get("/api/monitoring/status").json()
    assert body["enabled"] is True and body["cycles_completed"] == 2
    assert body["poll_interval_s"] == 5 and body["failure_confirmations"] == 3
    assert body["detection_time_s"] == 15  # interval x confirmations
    assert body["last_cycle_at"] and body["last_error"] is None


def test_devices_expose_live_monitoring_fields(monitored):
    monitored.cycles(3)
    switch = monitored.get("/api/devices/cse-switch").json()
    assert switch["status"] == "online" and switch["latest"]["source"] == "simulated"
    assert switch["latest"]["sent"] == 5 and switch["consecutive_failures"] == 0
    assert switch["caused_by"] is None and switch["monitoring_error"] is None


def test_failure_is_visible_through_the_api(monitored):
    monitored.cycles(3)
    monitored.fault("cse-switch", "offline")
    monitored.cycles(3)
    assert monitored.get("/api/devices/cse-switch").json()["status"] == "offline"
    pc = monitored.get("/api/devices/cse-pc-1").json()
    assert pc["status"] == "unreachable" and pc["caused_by"] == "cse-switch"
    events = monitored.get("/api/events", params={"limit": 6}).json()
    assert len(events) == 6 and {e["to_status"] for e in events} == {"offline", "unreachable"}
    only = monitored.get("/api/events", params={"device_id": "cse-switch"}).json()
    assert [e["to_status"] for e in only] == ["offline", "online"]  # newest first


def test_measurement_history(monitored):
    monitored.cycles(4)
    rows = monitored.get("/api/devices/cse-switch/measurements").json()
    assert len(rows) == 4 and rows[0]["ts"] <= rows[-1]["ts"]
    assert {"rtt_avg_ms", "loss_pct", "jitter_ms", "status", "source"} <= set(rows[0])
    assert len(monitored.get("/api/devices/cse-switch/measurements", params={"limit": 2}).json()) == 2
    assert monitored.get("/api/devices/ghost/measurements").status_code == 404
    assert monitored.get("/api/devices/cse-switch/measurements", params={"hours": 0}).status_code == 422
    assert monitored.get("/api/devices/cse-switch/measurements", params={"limit": 99999}).status_code == 422


def test_config_defaults_update_and_effect(monitored):
    body = monitored.get("/api/monitoring/config").json()
    assert body["source"] == "defaults" and body["config"]["failure_confirmations"] == 3
    assert body["config"]["thresholds"]["latency_warn_ms"] == 100

    new = {"poll_interval_s": 10, "failure_confirmations": 1, "recovery_confirmations": 2, "window_cycles": 5,
           "thresholds": {"latency_warn_ms": 80, "latency_crit_ms": 160, "loss_warn_pct": 5, "loss_crit_pct": 25, "util_warn_pct": 70, "util_crit_pct": 95}}
    saved = monitored.put("/api/monitoring/config", json=new)
    assert saved.status_code == 200 and saved.json()["source"] == "stored"
    assert monitored.get("/api/monitoring/config").json()["config"]["thresholds"]["util_warn_pct"] == 70
    assert monitored.get("/api/monitoring/status").json()["detection_time_s"] == 10

    monitored.cycles(3)
    monitored.fault("cse-pc-1", "offline")
    monitored.cycles(1)
    assert monitored.get("/api/devices/cse-pc-1").json()["status"] == "offline"  # confirmation count of 1 took effect


@pytest.mark.parametrize(
    "patch",
    [
        {"poll_interval_s": 0.1},
        {"failure_confirmations": 0},
        {"failure_confirmations": 99},
        {"window_cycles": 1},
        {"surprise": 1},
        {"thresholds": {"latency_warn_ms": 300, "latency_crit_ms": 200}},
        {"thresholds": {"loss_warn_pct": 50, "loss_crit_pct": 50}},
        {"thresholds": {"util_warn_pct": 120}},
        {"thresholds": {"latency_warn_ms": -5}},
        {"thresholds": {"nonsense": 5}},
    ],
)
def test_invalid_configuration_is_rejected(monitored, patch):
    assert monitored.put("/api/monitoring/config", json=patch).status_code == 422
    assert monitored.get("/api/monitoring/config").json()["source"] == "defaults"  # nothing was saved


def test_monitoring_routes_return_503_when_the_database_is_down(down_client):
    for path in ("/api/events", "/api/monitoring/config", "/api/monitoring/status"):
        assert down_client.get(path).status_code in (200, 503), path
    assert down_client.get("/api/events").status_code == 503
    assert down_client.get("/api/monitoring/config").status_code == 503
    assert down_client.get("/api/devices/cse-switch/measurements").status_code == 503
