import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_monitoring_store, get_store, get_traffic_engine, get_traffic_store
from app.config.settings import Settings
from app.main import create_app
from app.network_model.seed import seed_database
from app.simulator.faults import set_fault
from app.simulator.traffic import SimulatedTraffic
from app.traffic.engine import TrafficEngine
from tests.fakes import InMemoryMonitoringStore, InMemoryNetworkStore, InMemoryTrafficStore
from tests.test_traffic_engine import CONFIG, Clock, ScriptedHost

SETTINGS = Settings(_env_file=None)


@pytest.fixture
def traffic_client():
    network, traffic, monitoring = InMemoryNetworkStore(), InMemoryTrafficStore(), InMemoryMonitoringStore()
    asyncio.run(seed_database(network))
    engine = TrafficEngine(network, traffic, SimulatedTraffic(CONFIG), ScriptedHost(), SETTINGS, clock=Clock(recent=True))
    app = create_app()
    app.dependency_overrides[get_store] = lambda: network
    app.dependency_overrides[get_traffic_store] = lambda: traffic
    app.dependency_overrides[get_monitoring_store] = lambda: monitoring
    app.dependency_overrides[get_traffic_engine] = lambda: engine
    client = TestClient(app)
    client.__enter__()
    client.cycles = lambda n=1: [asyncio.run(engine.run_cycle()) for _ in range(n)]
    client.fault = lambda device, fault, **params: asyncio.run(set_fault(network, device, fault, params))
    yield client
    client.__exit__(None, None, None)


def test_status_when_disabled(seeded_client):
    assert seeded_client.get("/api/traffic/status").json() == {**seeded_client.get("/api/traffic/status").json(), "enabled": False, "running": False}


def test_status_when_running(traffic_client):
    traffic_client.cycles(3)
    body = traffic_client.get("/api/traffic/status").json()
    assert body["enabled"] and body["cycles_completed"] == 3 and body["counter_bits"] == 32
    assert body["host_label"] == "eth0" and body["host_error"] is None and body["interval_s"] == 5


def test_links_before_and_after_data(traffic_client):
    before = traffic_client.get("/api/traffic/links").json()
    assert len(before) == 16 and all(l["state"] == "unknown" and l["rx_mbps"] is None for l in before)
    traffic_client.cycles(3)
    after = {l["id"]: l for l in traffic_client.get("/api/traffic/links").json()}
    cse = after["core-switch--cse-switch"]
    assert cse["a_name"] == "Core L3 Switch" and cse["b_name"] == "CSE Switch" and cse["kind"] == "uplink" and cse["capacity_mbps"] == 100
    assert cse["state"] == "up" and cse["source"] == "simulated" and 0 < cse["util_pct"] < 100 and cse["rx_pps"] > 0


def test_summary_blocks_wan_backbone_and_real_host(traffic_client):
    traffic_client.cycles(3)
    body = traffic_client.get("/api/traffic/summary").json()
    assert [b["block"] for b in body["blocks"]] == ["cse", "library", "admin"]
    assert all(b["source"] == "simulated" and b["total_mbps"] > 0 for b in body["blocks"])
    assert body["blocks"][0]["total_mbps"] > body["blocks"][1]["total_mbps"] > body["blocks"][2]["total_mbps"]
    assert body["wan"]["kind"] == "wan" and body["backbone"]["kind"] == "backbone"
    assert body["campus_total_mbps"] == pytest.approx(sum(b["total_mbps"] for b in body["blocks"]))
    assert body["host"]["source"] == "real" and body["host"]["label"] == "eth0" and body["host"]["rx_mbps"] == pytest.approx(10.0)
    assert body["busiest_link"]["util_pct"] >= max(b["util_pct"] for b in body["blocks"])


def test_summary_before_any_data(traffic_client):
    body = traffic_client.get("/api/traffic/summary").json()
    assert body["blocks"] == [] and body["host"] is None and body["busiest_link"] is None


def test_congestion_is_visible_in_the_api(traffic_client):
    traffic_client.cycles(2)
    traffic_client.fault("admin-switch", "congestion", utilization_pct=97)
    traffic_client.cycles(2)
    links = {l["id"]: l for l in traffic_client.get("/api/traffic/links").json()}
    assert links["core-switch--admin-switch"]["state"] == "congested"
    assert links["core-switch--admin-switch"]["util_pct"] == pytest.approx(97, abs=0.5)
    summary = traffic_client.get("/api/traffic/summary").json()
    assert summary["busiest_link"]["id"] == "core-switch--admin-switch"


def test_protocols_are_labelled_simulated(traffic_client):
    traffic_client.cycles(4)
    body = traffic_client.get("/api/traffic/protocols", params={"minutes": 60}).json()
    assert body["source"] == "simulated" and body["total_bytes"] > 0 and "No packets" in body["note"]
    assert [p["name"] for p in body["protocols"]] == ["tcp", "udp", "dns", "icmp", "other"]
    assert sum(p["pct"] for p in body["protocols"]) == pytest.approx(100)
    assert traffic_client.get("/api/traffic/protocols", params={"minutes": 0}).status_code == 422


def test_link_history(traffic_client):
    traffic_client.cycles(6)
    rows = traffic_client.get("/api/traffic/links/core-switch--cse-switch/history").json()
    assert len(rows) == 5 and rows[0]["ts"] <= rows[-1]["ts"] and {"rx_mbps", "tx_mbps", "util_pct"} <= set(rows[0])
    assert len(traffic_client.get("/api/traffic/links/core-switch--cse-switch/history", params={"limit": 2}).json()) == 2
    bucketed = traffic_client.get("/api/traffic/links/core-switch--cse-switch/history", params={"bucket_s": 3600}).json()
    assert len(bucketed) == 1
    assert traffic_client.get("/api/traffic/links/ghost/history").status_code == 404
    assert traffic_client.get("/api/traffic/links/core-switch--cse-switch/history", params={"hours": 0}).status_code == 422
    assert traffic_client.get("/api/traffic/links/core-switch--cse-switch/history", params={"bucket_s": 99999}).status_code == 422


def test_block_and_host_history(traffic_client):
    traffic_client.cycles(5)
    blocks = traffic_client.get("/api/traffic/blocks/history", params={"bucket_s": 0}).json()
    assert len(blocks) == 4 and set(blocks[0]["blocks"]) == {"cse", "library", "admin"}
    assert {"rx_mbps", "tx_mbps", "total_mbps"} == set(blocks[0]["blocks"]["cse"])
    host = traffic_client.get("/api/traffic/host/history").json()
    assert len(host) == 4 and host[0]["rx_mbps"] == pytest.approx(10.0)


def test_traffic_routes_return_503_when_the_database_is_down(down_client):
    for path in ("/api/traffic/links", "/api/traffic/summary", "/api/traffic/protocols", "/api/traffic/blocks/history", "/api/traffic/host/history"):
        assert down_client.get(path).status_code == 503, path
    assert down_client.get("/api/traffic/status").status_code == 200  # reports from memory, not the database
