"""The full pipeline on the real driver: engine -> MongoDB -> API (skipped if no MongoDB is reachable)."""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient

from app.api.dependencies import get_engine
from app.config import get_settings
from app.config.settings import Settings
from app.main import create_app
from app.monitoring.engine import MonitoringEngine
from app.monitoring.store import MongoMonitoringStore
from app.network_model.seed import seed_database
from app.network_model.store import MongoNetworkStore
from app.probes.dispatcher import ProbeDispatcher
from app.simulator import SimulatedProbe
from app.simulator.faults import set_fault
from tests.conftest import TEST_MONGODB_URI, _mongo_reachable
from tests.test_engine import CLEAN, StubReal


@pytest.fixture
def pipeline(monkeypatch):
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

    class Handle:
        """Runs engine cycles and fault injections on throwaway clients bound to this test database."""

        def run(self, coroutine_factory):
            async def go():
                client = AsyncMongoClient(TEST_MONGODB_URI, tz_aware=True)
                try:
                    network, monitoring = MongoNetworkStore(client[db_name]), MongoMonitoringStore(client[db_name])
                    engine = MonitoringEngine(network, monitoring, ProbeDispatcher(StubReal(), SimulatedProbe(CLEAN)), Settings(_env_file=None))
                    return await coroutine_factory(network, monitoring, engine)
                finally:
                    await client.close()

            return asyncio.run(go())

    yield Handle()

    async def cleanup():
        client = AsyncMongoClient(TEST_MONGODB_URI)
        await client.drop_database(db_name)
        await client.close()

    asyncio.run(cleanup())
    get_settings.cache_clear()


def test_failure_detection_end_to_end_on_the_real_driver(pipeline):
    async def scenario(network, monitoring, engine):
        for _ in range(3):
            await engine.run_cycle()
        await set_fault(network, "cse-switch", "offline")
        for _ in range(3):
            await engine.run_cycle()
        devices = {d.id: d for d in await network.list_devices()}
        events = await monitoring.list_events(limit=100)
        history = await monitoring.list_measurements("cse-switch", limit=100)
        return devices, events, history

    devices, events, history = pipeline.run(scenario)
    assert devices["cse-switch"].status == "offline"
    assert {i for i, d in devices.items() if d.status == "unreachable"} == {"cse-ap", "cse-server", "cse-pc-1", "cse-pc-2", "cse-pc-3"}
    assert devices["cse-pc-1"].caused_by == "cse-switch" and devices["cse-pc-1"].latest.source == "simulated"
    assert sum(1 for e in events if e.to_status == "offline") == 1
    assert len(history) == 6 and history[-1].status == "offline" and history[-1].received == 0
    assert history[-1].ts.tzinfo is not None


def test_api_reads_what_the_engine_wrote_on_the_real_driver(pipeline):
    pipeline.run(lambda network, monitoring, engine: _cycles(engine, 3))
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        switch = client.get("/api/devices/cse-switch").json()
        assert switch["status"] == "online" and switch["latest"]["sent"] == 5
        assert len(client.get("/api/devices/cse-switch/measurements").json()) == 3
        assert client.put("/api/monitoring/config", json={"poll_interval_s": 8}).status_code == 200
        assert client.get("/api/monitoring/config").json()["source"] == "stored"
        assert len(client.get("/api/events").json()) == 17  # unknown -> online for every device


async def _cycles(engine, n):
    for _ in range(n):
        await engine.run_cycle()
