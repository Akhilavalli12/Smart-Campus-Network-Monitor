"""Traffic pipeline on the real driver: counters -> engine -> MongoDB -> API (skipped if no MongoDB is reachable)."""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient

from app.config import get_settings
from app.config.settings import Settings
from app.main import create_app
from app.network_model.seed import seed_database
from app.network_model.store import MongoNetworkStore
from app.simulator.faults import set_fault
from app.simulator.traffic import SimulatedTraffic
from app.traffic.engine import TrafficEngine
from app.traffic.store import MongoTrafficStore
from tests.conftest import TEST_MONGODB_URI, _mongo_reachable
from tests.test_traffic_engine import CONFIG, Clock, ScriptedHost


@pytest.fixture
def database(monkeypatch):
    if not asyncio.run(_mongo_reachable()):
        pytest.skip(f"MongoDB not reachable at {TEST_MONGODB_URI}")
    db_name = f"campus_noc_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("MONGODB_URI", TEST_MONGODB_URI)
    monkeypatch.setenv("MONGODB_DB_NAME", db_name)
    get_settings.cache_clear()

    async def prepare():
        client = AsyncMongoClient(TEST_MONGODB_URI, tz_aware=True)
        network = MongoNetworkStore(client[db_name])
        await network.ensure_indexes()
        await seed_database(network)
        await client.close()

    asyncio.run(prepare())
    yield db_name

    async def cleanup():
        client = AsyncMongoClient(TEST_MONGODB_URI)
        await client.drop_database(db_name)
        await client.close()

    asyncio.run(cleanup())
    get_settings.cache_clear()


def run_cycles(db_name, n, fault=None):
    async def go():
        client = AsyncMongoClient(TEST_MONGODB_URI, tz_aware=True)
        try:
            network, traffic = MongoNetworkStore(client[db_name]), MongoTrafficStore(client[db_name])
            engine = TrafficEngine(network, traffic, SimulatedTraffic(CONFIG), ScriptedHost(), Settings(_env_file=None), clock=Clock(recent=True))
            for i in range(n):
                if fault and i == fault[0]:
                    await set_fault(network, *fault[1])
                await engine.run_cycle()
        finally:
            await client.close()

    asyncio.run(go())


def test_pipeline_on_the_real_driver_including_32_bit_wraps(database):
    run_cycles(database, 200)  # 1000 simulated seconds: the busiest 32-bit counters wrap more than once
    with TestClient(create_app()) as client:
        links = {l["id"]: l for l in client.get("/api/traffic/links").json()}
        assert links["core-switch--cse-switch"]["rx_mbps"] > 0 and links["core-switch--cse-switch"]["state"] == "up"
        history = client.get("/api/traffic/links/internet--edge-router/history", params={"limit": 5000}).json()
        assert len(history) == 199  # no gap even though the counters wrapped
        assert max(p["rx_mbps"] for p in history) - min(p["rx_mbps"] for p in history) < 0.01 * max(p["rx_mbps"] for p in history)
        summary = client.get("/api/traffic/summary").json()
        assert len(summary["blocks"]) == 3 and summary["host"]["source"] == "real"
        assert client.get("/api/traffic/protocols", params={"minutes": 60}).json()["total_bytes"] > 0


def test_congestion_end_to_end_on_the_real_driver(database):
    run_cycles(database, 6, fault=(3, ("cse-switch", "congestion", {"utilization_pct": 95})))
    with TestClient(create_app()) as client:
        link = next(l for l in client.get("/api/traffic/links").json() if l["id"] == "core-switch--cse-switch")
        assert link["state"] == "congested" and link["util_pct"] == pytest.approx(95, abs=0.5)
